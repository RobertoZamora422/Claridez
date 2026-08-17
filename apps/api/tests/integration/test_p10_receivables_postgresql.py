from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from claridez.application.reservation_confirmation import confirm_reservation
from claridez.commercial.public import accepted_quotation_snapshot
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.errors import ReceivablesError
from claridez.receivables.models import (
    CollectionScheduleRevision,
    FinancialCommand,
    MovementReversal,
    PaymentApplication,
    ReceivableAdjustment,
    ReceivableObligation,
    ReceivedPayment,
    RefundRecord,
)
from claridez.receivables.services import (
    apply_payment_authorized,
    record_payment_authorized,
    record_refund_authorized,
    reverse_movement_authorized,
    revise_schedule_authorized,
)
from claridez.scheduling.models import Reservation, ScheduleEvent
from claridez.settings.environment import load_bootstrap_settings
from tests.test_receivables import _confirmed, _provisional

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

PRIVATE_TABLES = (
    "receivables_receivableobligation",
    "receivables_collectionschedulerevision",
    "receivables_collectionscheduledue",
    "receivables_receivedpayment",
    "receivables_paymentapplication",
    "receivables_receivableadjustment",
    "receivables_movementreversal",
    "receivables_refundrecord",
    "receivables_refundapplication",
    "receivables_receipt",
    "receivables_receiptsequence",
    "receivables_financialcommand",
    "receivables_financialevent",
    "receivables_legacyevidencereview",
    "receivables_financialevidencelink",
)


def _app_connection() -> psycopg.Connection[tuple[object, ...]]:
    settings = load_bootstrap_settings()
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.test_db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        autocommit=True,
    )


def _payment(
    owner: User,
    organization_id: UUID,
    person_id: UUID,
    *,
    value: str,
    suffix: str,
) -> ReceivedPayment:
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_RECORD_PAYMENT
    ) as authorization:
        return record_payment_authorized(
            authorization,
            counterparty_person_id=person_id,
            amount_value=value,
            currency_value="USD",
            reported_at=timezone.now() + timedelta(seconds=uuid4().int % 1000),
            method="cash",
            reference=f"RACE-{suffix}",
            observation="Carrera PostgreSQL P10",
            provenance="manual",
            evidence_level="internal_report",
            idempotency_key=uuid4(),
        )


def _run_concurrently(operation: Callable[[], str]) -> list[str]:
    barrier = Barrier(2)

    def execute() -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            return operation()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(execute), pool.submit(execute))
        return [future.result(timeout=40) for future in futures]


def test_same_confirmation_key_is_atomic_and_creates_one_financial_chain() -> None:
    owner, creation, _, _, reservation = _provisional("p10-confirm-race")
    organization_id = creation.organization.pk
    key = uuid4()
    reported_at = timezone.now()

    def operation() -> str:
        actor = User.objects.get(pk=owner.pk)
        result = confirm_reservation(
            actor,
            organization_id,
            reservation_id=reservation["id"],
            kind="external_deposit",
            recognized_amount=Decimal("300.00"),
            reported_at=reported_at,
            reference="CONFIRM-RACE",
            payment_method="bank_transfer",
            idempotency_key=key,
        )
        return str(result["id"])

    results = _run_concurrently(operation)
    assert len(set(results)) == 1
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        assert ReceivableObligation.objects.count() == 1
        assert ReceivedPayment.objects.count() == 1
        assert PaymentApplication.objects.count() == 1
        assert FinancialCommand.objects.filter(command_type="confirm_reservation").count() == 1


def test_same_payment_key_is_serialized_and_replayed_once() -> None:
    owner, creation, person, _, _, _ = _confirmed("p10-payment-key-race")
    organization_id = creation.organization.pk
    key = uuid4()
    reported_at = timezone.now() + timedelta(minutes=5)

    def operation() -> str:
        actor = User.objects.get(pk=owner.pk)
        with authorized_tenant_scope(
            actor, organization_id, Capability.RECEIVABLES_RECORD_PAYMENT
        ) as authorization:
            payment = record_payment_authorized(
                authorization,
                counterparty_person_id=person["id"],
                amount_value="75.00",
                currency_value="USD",
                reported_at=reported_at,
                method="cash",
                reference="SAME-KEY",
                observation="Retry concurrente",
                provenance="manual",
                evidence_level="internal_report",
                idempotency_key=key,
            )
            return str(payment.pk)

    results = _run_concurrently(operation)
    assert len(set(results)) == 1
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        assert ReceivedPayment.objects.filter(reference="SAME-KEY").count() == 1


def test_concurrent_applications_cannot_exhaust_payment_or_obligation_twice() -> None:
    owner, creation, person, _, _, _ = _confirmed("p10-application-race")
    organization_id = creation.organization.pk
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        obligation_id = ReceivableObligation.objects.get().pk
    payment = _payment(owner, organization_id, person["id"], value="100.00", suffix="PAYMENT")

    def same_payment() -> str:
        actor = User.objects.get(pk=owner.pk)
        try:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_APPLY_PAYMENT
            ) as authorization:
                row = apply_payment_authorized(
                    authorization,
                    payment_id=payment.pk,
                    obligation_id=obligation_id,
                    amount_value="80.00",
                    idempotency_key=uuid4(),
                )
                return str(row.pk)
        except ReceivablesError as error:
            return error.code

    results = _run_concurrently(same_payment)
    assert sum(value == "payment_overallocated" for value in results) == 1

    first = _payment(owner, organization_id, person["id"], value="800.00", suffix="BALANCE-A")
    second = _payment(owner, organization_id, person["id"], value="800.00", suffix="BALANCE-B")
    barrier = Barrier(2)

    def same_obligation(payment_id: UUID) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=20)
            try:
                with authorized_tenant_scope(
                    actor, organization_id, Capability.RECEIVABLES_APPLY_PAYMENT
                ) as authorization:
                    row = apply_payment_authorized(
                        authorization,
                        payment_id=payment_id,
                        obligation_id=obligation_id,
                        amount_value="800.00",
                        idempotency_key=uuid4(),
                    )
                    return str(row.pk)
            except ReceivablesError as error:
                return error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(same_obligation, first.pk),
            pool.submit(same_obligation, second.pk),
        )
        results = [future.result(timeout=40) for future in futures]
    assert sum(value == "obligation_overallocated" for value in results) == 1


def test_concurrent_reversal_refund_and_schedule_commands_are_serialized() -> None:
    owner, creation, person, _, _, _ = _confirmed("p10-other-races")
    organization_id = creation.organization.pk
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        obligation = ReceivableObligation.objects.get()
    payment = _payment(owner, organization_id, person["id"], value="100.00", suffix="OTHER")
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_APPLY_PAYMENT
    ) as authorization:
        application = apply_payment_authorized(
            authorization,
            payment_id=payment.pk,
            obligation_id=obligation.pk,
            amount_value="20.00",
            idempotency_key=uuid4(),
        )

    def reverse() -> str:
        actor = User.objects.get(pk=owner.pk)
        try:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_REVERSE_MOVEMENT
            ) as authorization:
                row = reverse_movement_authorized(
                    authorization,
                    target_kind="application",
                    target_id=application.pk,
                    reason="Corrección concurrente completa",
                    idempotency_key=uuid4(),
                )
                return str(row.pk)
        except ReceivablesError as error:
            return error.code

    reversal_results = _run_concurrently(reverse)
    assert sum(value == "movement_already_reversed" for value in reversal_results) == 1

    def refund() -> str:
        actor = User.objects.get(pk=owner.pk)
        try:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_RECORD_REFUND
            ) as authorization:
                row = record_refund_authorized(
                    authorization,
                    payment_id=payment.pk,
                    amount_value="80.00",
                    currency_value="USD",
                    refunded_at=timezone.now(),
                    method="cash",
                    reference="REFUND-RACE",
                    reason="Devolución externa concurrente",
                    idempotency_key=uuid4(),
                )
                return str(row.pk)
        except ReceivablesError as error:
            return error.code

    refund_results = _run_concurrently(refund)
    refund_conflicts = {"refund_exceeds_available", "refund_exceeds_unapplied"}
    assert sum(value in refund_conflicts for value in refund_results) == 1

    def schedule() -> str:
        actor = User.objects.get(pk=owner.pk)
        with authorized_tenant_scope(
            actor, organization_id, Capability.RECEIVABLES_MANAGE_SCHEDULE
        ) as authorization:
            row = revise_schedule_authorized(
                authorization,
                obligation_id=obligation.pk,
                dues=[
                    {
                        "due_key": uuid4(),
                        "amount": Decimal("1617.20"),
                        "due_on": date.today() + timedelta(days=30),
                    }
                ],
                provenance="manual",
                reason="Revisión concurrente",
                idempotency_key=uuid4(),
            )
            return str(row.revision)

    schedule_results = sorted(_run_concurrently(schedule))
    assert schedule_results == ["1", "2"]
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        assert MovementReversal.objects.filter(target_id=application.pk).count() == 1
        assert RefundRecord.objects.filter(payment=payment).count() == 1
        assert CollectionScheduleRevision.objects.filter(obligation=obligation).count() == 2


def test_force_rls_privileges_and_app_sql_protect_financial_history() -> None:
    first_owner, first, _, _, _, _ = _confirmed("p10-rls-a")
    second_owner, second, _, _, _, _ = _confirmed("p10-rls-b")
    del second_owner
    with authorized_tenant_scope(first_owner, first.organization.pk, Capability.RECEIVABLES_READ):
        payment_id = ReceivedPayment.objects.get().pk
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s) ORDER BY relname",
            [list(PRIVATE_TABLES)],
        )
        assert cursor.fetchall() == sorted((table, True, True) for table in PRIVATE_TABLES)
        cursor.execute(
            "SELECT has_table_privilege('claridez_app', "
            "'receivables_receivedpayment', 'UPDATE'), "
            "has_table_privilege('claridez_app', 'receivables_receivedpayment', 'DELETE'), "
            "has_table_privilege('claridez_app', 'receivables_receivedpayment', 'TRUNCATE')"
        )
        assert cursor.fetchone() == (False, False, False)

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(first.organization.pk),),
        )
        cursor.execute("SELECT organization_id FROM receivables_receivedpayment")
        assert {row[0] for row in cursor.fetchall()} == {first.organization.pk}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE receivables_receivedpayment SET amount = 1 WHERE id = %s",
                (payment_id,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("DELETE FROM receivables_receivedpayment WHERE id = %s", (payment_id,))


def test_deferred_guard_rejects_obligation_for_unconfirmed_root() -> None:
    owner, creation, _, _, reservation = _provisional("p10-deferred-guard")
    organization_id = creation.organization.pk
    with (
        authorized_tenant_scope(
            owner, organization_id, Capability.RECEIVABLES_READ
        ) as authorization,
        pytest.raises(IntegrityError),
        transaction.atomic(),
    ):
        reservation_row = Reservation.objects.get(pk=reservation["id"])
        quotation = accepted_quotation_snapshot(authorization, reservation_row.quotation_version_id)
        event = ScheduleEvent.objects.filter(reservation_id=reservation["id"]).first()
        assert event is not None
        ReceivableObligation.objects.create(
            organization_id=organization_id,
            root_reservation_id=reservation_row.root_id,
            confirmation_source_id=reservation["id"],
            confirmation_event_id=event.pk,
            event_request_id=quotation.event_request_id,
            quotation_version_id=quotation.id,
            quotation_visible_number=quotation.visible_number,
            quotation_version=quotation.version,
            counterparty_person_id=quotation.person_id,
            counterparty_name_snapshot=quotation.person_name,
            currency=quotation.currency,
            subtotal=quotation.subtotal,
            discount_total=quotation.discount_total,
            original_total=quotation.total,
            economic_terms_snapshot={},
            confirmed_at=timezone.now(),
            created_by_membership_id=authorization.membership_id,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_orm_bulk_paths_cannot_mutate_or_delete_consumed_facts() -> None:
    owner, creation, _, _, _, _ = _confirmed("p10-bulk-guards")
    organization_id = creation.organization.pk
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        obligation = ReceivableObligation.objects.get()
        payment = ReceivedPayment.objects.get()
        payment.amount = Decimal("1.00")
        with pytest.raises(DatabaseError), transaction.atomic():
            ReceivedPayment.objects.bulk_update([payment], ["amount"])
        with pytest.raises(DatabaseError), transaction.atomic():
            ReceivableObligation.objects.filter(pk=obligation.pk).update(
                original_total=Decimal("1.00")
            )
        with pytest.raises(DatabaseError), transaction.atomic():
            PaymentApplication.objects.all().delete()


def test_partial_schedule_is_valid_and_adjustments_cannot_make_it_exceed_obligation() -> None:
    owner, creation, _, _, _, _ = _confirmed("p10-partial-schedule", kind="waiver")
    organization_id = creation.organization.pk
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_MANAGE_SCHEDULE
    ) as authorization:
        obligation = ReceivableObligation.objects.get()
        revision = revise_schedule_authorized(
            authorization,
            obligation_id=obligation.pk,
            dues=[
                {
                    "due_key": uuid4(),
                    "amount": Decimal("1000.00"),
                    "due_on": date(2026, 12, 1),
                }
            ],
            provenance="manual",
            reason="Calendario parcial con remanente sin vencimiento",
            idempotency_key=uuid4(),
        )
        assert revision.revision == 1

    with (
        authorized_tenant_scope(
            owner, organization_id, Capability.RECEIVABLES_RECORD_ADJUSTMENT
        ) as authorization,
        pytest.raises(IntegrityError),
        transaction.atomic(),
    ):
        ReceivableAdjustment.objects.create(
            organization_id=organization_id,
            obligation_id=obligation.pk,
            direction=ReceivableAdjustment.Direction.DECREASE,
            amount=Decimal("700.00"),
            currency="USD",
            reason="Bypass ORM que dejaría calendario superior a obligación",
            recorded_by_membership_id=authorization.membership_id,
            occurred_at=timezone.now(),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        assert ReceivableAdjustment.objects.count() == 0
