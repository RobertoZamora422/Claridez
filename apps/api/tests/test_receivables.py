from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from claridez.application.reservation_confirmation import confirm_reservation
from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.services import (
    accept_quotation_version,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    replace_quotation_draft,
)
from claridez.documents.models import ContractualInstrument, ContractualRecord
from claridez.identity.models import User
from claridez.operations.models import EventPreparation
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.models import Membership
from claridez.organizations.services import (
    OrganizationCreation,
    add_membership,
    create_organization,
)
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.errors import ReceivablesError
from claridez.receivables.models import (
    CollectionScheduleRevision,
    FinancialCommand,
    MovementReversal,
    PaymentApplication,
    Receipt,
    ReceivableObligation,
    ReceivedPayment,
    RefundRecord,
)
from claridez.receivables.money import amount, currency
from claridez.receivables.services import (
    aging_authorized,
    apply_payment_authorized,
    issue_receipt_authorized,
    obligation_aging,
    obligation_balance,
    obligation_data,
    payment_available,
    portfolio_authorized,
    record_adjustment_authorized,
    record_payment_authorized,
    record_refund_authorized,
    reverse_movement_authorized,
    revise_schedule_authorized,
    statement_authorized,
)
from claridez.scheduling.models import Reservation
from claridez.scheduling.services import cancel_reservation, reschedule_reservation

PASSWORD = "correct-horse-battery-staple-receivables-42"


def _login(client: Client, user: User) -> str:
    csrf = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": user.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _owner(slug: str) -> tuple[User, OrganizationCreation]:
    owner = User.objects.create_user(
        email=f"{slug}@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    return owner, create_organization(owner_user_id=owner.pk, name=f"Organización {slug}")


def _person(owner: User, organization_id: UUID) -> dict[str, Any]:
    return create_person(
        owner,
        organization_id,
        full_name="María Pérez",
        phone="0991234567",
        email=f"maria-{organization_id}@example.com",
        origin="whatsapp",
        origin_detail=None,
    )


def _request(
    owner: User,
    organization_id: UUID,
    person_id: UUID | str,
    *,
    days_from_now: int = 20,
) -> dict[str, Any]:
    event_type = next(
        (row for row in list_event_types(owner, organization_id) if row["name"] == "Boda"),
        None,
    )
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name="Boda")
    start = timezone.now() + timedelta(days=days_from_now)
    return create_event_request(
        owner,
        organization_id,
        person_id=person_id,
        event_type_id=event_type["id"],
        space_id=list_venues(owner, organization_id)[0]["spaces"][0]["id"],
        starts_at=start,
        ends_at=start + timedelta(hours=5),
        estimated_guests=120,
        general_need="Recepción completa",
        notes="Caso P10",
        origin="referral",
        origin_detail="Cliente anterior",
    )


def _accepted(
    owner: User, organization_id: UUID, request_id: UUID | str
) -> tuple[dict[str, Any], dict[str, Any]]:
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=request_id,
        valid_until=timezone.now() + timedelta(days=3),
    )
    quotation = replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=quotation["versions"][0]["revision"],
        valid_until=timezone.now() + timedelta(days=3),
        notes="Propuesta comercial",
        lines=[
            {
                "description": "Alquiler del salón",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("1000.00"),
                "discount_amount": Decimal("50.00"),
            },
            {
                "description": "Servicio por invitado",
                "unit_label": "persona",
                "quantity": Decimal("120.000"),
                "unit_price": Decimal("5.555"),
                "discount_amount": Decimal("0.00"),
            },
        ],
    )
    issue_quotation_version(owner, organization_id, quotation_id=quotation["id"], version=1)
    reservation = accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="whatsapp",
        note="Aceptada por el cliente",
    )
    return quotation, reservation


def _provisional(
    slug: str = "receivables",
) -> tuple[User, OrganizationCreation, dict[str, Any], dict[str, Any], dict[str, Any]]:
    owner, creation = _owner(slug)
    person = _person(owner, creation.organization.pk)
    event_request = _request(owner, creation.organization.pk, person["id"])
    _, reservation = _accepted(owner, creation.organization.pk, event_request["id"])
    return owner, creation, person, event_request, reservation


def _confirmed(
    slug: str = "receivables-confirmed", *, kind: str = "external_deposit"
) -> tuple[
    User,
    OrganizationCreation,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    owner, creation, person, event_request, reservation = _provisional(slug)
    data = {
        "reservation_id": reservation["id"],
        "kind": kind,
        "idempotency_key": uuid4(),
    }
    if kind == "external_deposit":
        data.update(
            {
                "recognized_amount": Decimal("300.00"),
                "reported_at": timezone.now(),
                "reference": "TRX-P10-001",
                "payment_method": "bank_transfer",
            }
        )
    else:
        data["waiver_reason"] = "Exención comercial aprobada"
    confirmed = confirm_reservation(owner, creation.organization.pk, **data)
    return owner, creation, person, event_request, reservation, confirmed


def test_money_rounds_half_up_and_rejects_non_iso_currency() -> None:
    assert amount("1.005") == Decimal("1.01")
    assert amount("0") == Decimal("0.00")
    assert currency("usd") == "USD"
    with pytest.raises(ValueError):
        currency("US")


@pytest.mark.django_db
def test_confirmation_creates_exact_obligation_and_deposit_once() -> None:
    owner, creation, _, event_request, reservation, confirmed = _confirmed()
    assert confirmed["status"] == "confirmed"
    with authorized_tenant_scope(
        owner, creation.organization.pk, Capability.RECEIVABLES_READ
    ) as authorization:
        obligation = ReceivableObligation.objects.get(root_reservation_id=reservation["root_id"])
        payment = ReceivedPayment.objects.get(confirmation_source_id=reservation["id"])
        application = PaymentApplication.objects.get(payment=payment, obligation=obligation)
        assert obligation.event_request_id == event_request["id"]
        assert obligation.original_total == Decimal("1617.20")
        assert obligation.subtotal == Decimal("1667.20")
        assert obligation.discount_total == Decimal("50.00")
        assert obligation.currency == "USD"
        assert payment.amount == application.amount == Decimal("300.00")
        assert payment.provenance == ReceivedPayment.Provenance.CONFIRMATION_DEPOSIT
        assert obligation_balance(obligation) == Decimal("1317.20")
        assert obligation_data(authorization, obligation)["schedule_configured"] is False
        confirmation_key = FinancialCommand.objects.get(
            command_type="confirm_reservation"
        ).idempotency_key

    replay = confirm_reservation(
        owner,
        creation.organization.pk,
        reservation_id=reservation["id"],
        kind="external_deposit",
        recognized_amount=Decimal("300.00"),
        reported_at=payment.reported_at,
        reference="TRX-P10-001",
        payment_method="bank_transfer",
        idempotency_key=confirmation_key,
    )
    assert replay["id"] == confirmed["id"]
    second_command = confirm_reservation(
        owner,
        creation.organization.pk,
        reservation_id=reservation["id"],
        kind="external_deposit",
        recognized_amount=Decimal("300.00"),
        reported_at=payment.reported_at,
        reference="TRX-P10-001",
        payment_method="bank_transfer",
        idempotency_key=uuid4(),
    )
    assert second_command["id"] == confirmed["id"]
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.RECEIVABLES_READ):
        assert ReceivableObligation.objects.count() == 1
        assert ReceivedPayment.objects.count() == 1
        assert PaymentApplication.objects.count() == 1
        assert FinancialCommand.objects.filter(command_type="confirm_reservation").count() == 2


@pytest.mark.django_db
def test_waiver_creates_obligation_without_payment() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("receivables-waiver", kind="waiver")
    assert confirmed["confirmation_kind"] == "waiver"
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.RECEIVABLES_READ):
        assert ReceivableObligation.objects.count() == 1
        assert ReceivedPayment.objects.count() == 0
        assert PaymentApplication.objects.count() == 0


@pytest.mark.django_db
def test_portfolio_and_aging_use_bounded_queries() -> None:
    owner, creation = _owner("receivables-bounded-reads")
    person = _person(owner, creation.organization.pk)
    for position in range(3):
        event_request = _request(
            owner,
            creation.organization.pk,
            person["id"],
            days_from_now=20 + position * 10,
        )
        _, reservation = _accepted(owner, creation.organization.pk, event_request["id"])
        confirm_reservation(
            owner,
            creation.organization.pk,
            reservation_id=reservation["id"],
            kind="waiver",
            waiver_reason="Exención aprobada para prueba de lectura por lote",
            idempotency_key=uuid4(),
        )

    with authorized_tenant_scope(
        owner,
        creation.organization.pk,
        Capability.RECEIVABLES_READ,
    ) as authorization:
        with CaptureQueriesContext(connection) as portfolio_queries:
            portfolio = portfolio_authorized(authorization)
        with CaptureQueriesContext(connection) as aging_queries:
            aging = aging_authorized(authorization)

    obligations = portfolio["obligations"]
    entries = aging["entries"]
    assert isinstance(obligations, list)
    assert isinstance(entries, list)
    assert len(obligations) == 3
    assert len(entries) == 3
    assert len(portfolio_queries) <= 8
    assert len(aging_queries) <= 9


@pytest.mark.django_db
def test_reschedule_and_cancel_preserve_the_same_financial_history() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("receivables-schedule-history")
    organization_id = creation.organization.pk
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        obligation = ReceivableObligation.objects.get()
        original_root = obligation.root_reservation_id
        original_balance = obligation_balance(obligation)
        original_payment_ids = tuple(ReceivedPayment.objects.values_list("id", flat=True))
        original_application_ids = tuple(PaymentApplication.objects.values_list("id", flat=True))

    result = reschedule_reservation(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        revision=confirmed["revision"],
        idempotency_key=uuid4(),
        space_id=confirmed["space_id"],
        starts_at_local=datetime(2026, 10, 20, 18, 0),
        ends_at_local=datetime(2026, 10, 20, 23, 0),
        timezone_name="America/Guayaquil",
        reason="Cambio de fecha sin cambio comercial",
        commercial_terms_unchanged=True,
    )
    successor_id = result["reservation"]["id"]
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        same = ReceivableObligation.objects.get()
        assert same.root_reservation_id == original_root
        assert obligation_balance(same) == original_balance
        assert tuple(ReceivedPayment.objects.values_list("id", flat=True)) == original_payment_ids
        assert (
            tuple(PaymentApplication.objects.values_list("id", flat=True))
            == original_application_ids
        )
        assert obligation_data(authorization, same)["current_reservation_id"] == successor_id

    cancelled = cancel_reservation(
        owner,
        organization_id,
        reservation_id=successor_id,
        reason="Cancelación que requiere decisión financiera explícita",
    )
    assert cancelled["status"] == Reservation.Status.CANCELLED
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        same = ReceivableObligation.objects.get()
        projection = obligation_data(authorization, same)
        assert obligation_balance(same) == original_balance
        assert projection["financial_review_required"] is True
        assert ReceivableObligation.objects.count() == 1
        assert tuple(ReceivedPayment.objects.values_list("id", flat=True)) == original_payment_ids
        assert (
            tuple(PaymentApplication.objects.values_list("id", flat=True))
            == original_application_ids
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure_target",
    [
        "claridez.scheduling.public.confirm_prepared",
        "claridez.application.reservation_confirmation.create_obligation_authorized",
        "claridez.application.reservation_confirmation.apply_payment_authorized",
        "claridez.operations.public.initialize_from_accepted_snapshot",
    ],
    ids=["scheduling", "obligation", "application", "commercial-operations"],
)
def test_confirmation_rolls_back_every_stage(
    monkeypatch: pytest.MonkeyPatch, failure_target: str
) -> None:
    owner, creation, _, _, reservation = _provisional(
        f"recv-rollback-{failure_target.rsplit('.', maxsplit=1)[-1][:12]}"
    )

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("fallo inyectado P10")

    monkeypatch.setattr(failure_target, fail)
    with pytest.raises(RuntimeError, match="fallo inyectado P10"):
        confirm_reservation(
            owner,
            creation.organization.pk,
            reservation_id=reservation["id"],
            kind="external_deposit",
            recognized_amount=Decimal("300.00"),
            reported_at=timezone.now(),
            reference="ROLLBACK-P10",
            payment_method="bank_transfer",
            idempotency_key=uuid4(),
        )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.RECEIVABLES_READ):
        row = Reservation.objects.get(pk=reservation["id"])
        assert row.status == Reservation.Status.PROVISIONAL
        assert ReceivableObligation.objects.count() == 0
        assert ReceivedPayment.objects.count() == 0
        assert PaymentApplication.objects.count() == 0
        assert FinancialCommand.objects.count() == 0
        assert EventPreparation.objects.count() == 0


@pytest.mark.django_db
def test_schedule_payments_adjustments_refunds_receipt_and_statement_are_algebraic() -> None:
    owner, creation, person, _, _, _ = _confirmed("receivables-ledger")
    organization_id = creation.organization.pk
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        obligation = ReceivableObligation.objects.get()
        due_one, due_two = uuid4(), uuid4()
        revision = revise_schedule_authorized(
            authorization,
            obligation_id=obligation.pk,
            dues=[
                {"due_key": due_one, "amount": Decimal("800.00"), "due_on": date(2026, 8, 1)},
                {"due_key": due_two, "amount": Decimal("700.00"), "due_on": date(2026, 9, 1)},
            ],
            provenance="manual",
            reason="Calendario operativo inicial",
            idempotency_key=uuid4(),
        )
        assert revision.revision == 1
        entries = obligation_aging(obligation, date(2026, 8, 15))
        assert entries[0]["bucket"] == "1_30"
        assert entries[0]["days_overdue"] == 14
        assert entries[-1]["bucket"] == "unscheduled"
        assert entries[-1]["open_amount"] == Decimal("117.20")

        payment = record_payment_authorized(
            authorization,
            counterparty_person_id=person["id"],
            root_reservation_id=obligation.root_reservation_id,
            amount_value=Decimal("1500.00"),
            currency_value="USD",
            reported_at=timezone.now() + timedelta(seconds=1),
            method="cash",
            reference="",
            observation="Pago superior al saldo disponible",
            provenance="manual",
            evidence_level="internal_report",
            idempotency_key=uuid4(),
        )
        application = apply_payment_authorized(
            authorization,
            payment_id=payment.pk,
            obligation_id=obligation.pk,
            due_key=due_one,
            amount_value=Decimal("500.00"),
            idempotency_key=uuid4(),
        )
        assert payment_available(payment) == Decimal("1000.00")
        assert obligation_balance(obligation) == Decimal("817.20")

        adjustment = record_adjustment_authorized(
            authorization,
            obligation_id=obligation.pk,
            direction="increase",
            amount_value=Decimal("10.00"),
            currency_value="USD",
            reason="Corrección financiera documentada",
            idempotency_key=uuid4(),
        )
        assert obligation_balance(obligation) == Decimal("827.20")
        reverse_movement_authorized(
            authorization,
            target_kind="adjustment",
            target_id=adjustment.pk,
            reason="Se comprobó que el ajuste no procedía",
            idempotency_key=uuid4(),
        )
        assert obligation_balance(obligation) == Decimal("817.20")

        refund = record_refund_authorized(
            authorization,
            payment_id=payment.pk,
            obligation_id=obligation.pk,
            amount_value=Decimal("100.00"),
            currency_value="USD",
            refunded_at=timezone.now(),
            method="cash",
            reference="DEV-001",
            reason="Devolución externa declarada",
            allocations=[{"application_id": application.pk, "amount": Decimal("100.00")}],
            idempotency_key=uuid4(),
        )
        assert obligation_balance(obligation) == Decimal("917.20")
        assert payment_available(payment) == Decimal("1000.00")
        receipt = issue_receipt_authorized(
            authorization, payment_id=payment.pk, idempotency_key=uuid4()
        )
        assert receipt.visible_number == "RC-2026-000001"
        assert receipt.document_artifact_id is not None
        assert receipt.snapshot["label"] == "recibo/comprobante de cobro — no factura"
        with CaptureQueriesContext(connection) as statement_queries:
            statement = statement_authorized(authorization, obligation.pk)
        assert statement["balance"] == Decimal("917.20")
        assert len(statement_queries) <= 18
        refunds = statement["refunds"]
        receipts = statement["receipts"]
        assert isinstance(refunds, list) and len(refunds) == 1
        assert isinstance(receipts, list) and len(receipts) == 1
        issued_snapshot = receipt.snapshot

        reverse_movement_authorized(
            authorization,
            target_kind="refund",
            target_id=refund.pk,
            reason="La devolución fue registrada sobre el pago incorrecto",
            idempotency_key=uuid4(),
        )
        assert obligation_balance(obligation) == Decimal("817.20")
        receipt.refresh_from_db()
        assert receipt.snapshot == issued_snapshot
        assert ContractualRecord.objects.count() == 0
        assert ContractualInstrument.objects.count() == 0


@pytest.mark.django_db
def test_idempotency_conflict_overallocation_duplicate_review_and_immutability() -> None:
    owner, creation, person, _, _, _ = _confirmed("receivables-invariants")
    with authorized_tenant_scope(
        owner, creation.organization.pk, Capability.RECEIVABLES_READ
    ) as authorization:
        obligation = ReceivableObligation.objects.get()
        key = uuid4()
        reported = timezone.now() + timedelta(minutes=1)
        payment = record_payment_authorized(
            authorization,
            counterparty_person_id=person["id"],
            amount_value="20.00",
            currency_value="USD",
            reported_at=reported,
            method="cash",
            reference="",
            observation="",
            provenance="manual",
            evidence_level="internal_report",
            idempotency_key=key,
        )
        replay = record_payment_authorized(
            authorization,
            counterparty_person_id=person["id"],
            amount_value="20.00",
            currency_value="USD",
            reported_at=reported,
            method="cash",
            reference="",
            observation="",
            provenance="manual",
            evidence_level="internal_report",
            idempotency_key=key,
        )
        assert replay.pk == payment.pk
        with pytest.raises(ReceivablesError, match="solicitud diferente"):
            record_payment_authorized(
                authorization,
                counterparty_person_id=person["id"],
                amount_value="21.00",
                currency_value="USD",
                reported_at=reported,
                method="cash",
                reference="",
                observation="",
                provenance="manual",
                evidence_level="internal_report",
                idempotency_key=key,
            )
        with pytest.raises(ReceivablesError) as duplicate:
            record_payment_authorized(
                authorization,
                counterparty_person_id=person["id"],
                amount_value="20.00",
                currency_value="USD",
                reported_at=reported,
                method="cash",
                reference="",
                observation="",
                provenance="manual",
                evidence_level="internal_report",
                idempotency_key=uuid4(),
            )
        assert duplicate.value.code == "possible_duplicate_payment"
        with pytest.raises(ReceivablesError) as overallocated:
            apply_payment_authorized(
                authorization,
                payment_id=payment.pk,
                obligation_id=obligation.pk,
                amount_value="20.01",
                idempotency_key=uuid4(),
            )
        assert overallocated.value.code == "payment_overallocated"

        with pytest.raises(DatabaseError), transaction.atomic():
            ReceivedPayment.objects.filter(pk=payment.pk).update(amount=Decimal("1.00"))
        with pytest.raises(DatabaseError), transaction.atomic():
            payment.delete()

    with authorized_tenant_scope(owner, creation.organization.pk, Capability.RECEIVABLES_READ):
        assert MovementReversal.objects.count() == 0
        assert RefundRecord.objects.count() == 0
        assert CollectionScheduleRevision.objects.count() == 0
        assert Receipt.objects.count() == 0


@pytest.mark.django_db
def test_http_requires_session_csrf_capability_tenant_scope_and_idempotency() -> None:
    owner, creation, person, _, reservation, _ = _confirmed("receivables-http")
    foreign_owner, foreign = _owner("receivables-http-foreign")
    del foreign_owner
    organization_id = creation.organization.pk
    client = Client(enforce_csrf_checks=True)
    anonymous = client.get(f"/api/v1/organizations/{organization_id}/receivables/portfolio/")
    assert anonymous.status_code == 401
    csrf = _login(client, owner)
    base = f"/api/v1/organizations/{organization_id}/receivables"
    portfolio = client.get(f"{base}/portfolio/")
    assert portfolio.status_code == 200
    assert portfolio.json()["obligations"][0]["root_reservation_id"] == str(reservation["root_id"])

    payload = {
        "counterparty_person_id": str(person["id"]),
        "root_reservation_id": reservation["root_id"],
        "amount": "10.00",
        "currency": "USD",
        "reported_at": timezone.now().isoformat(),
        "method": "cash",
        "reference": "",
        "observation": "Prueba HTTP",
        "evidence_level": "internal_report",
    }
    missing_csrf = client.post(
        f"{base}/payments/",
        data=payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert missing_csrf.status_code == 403
    missing_key = client.post(
        f"{base}/payments/",
        data=payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "invalid_idempotency_key"
    created = client.post(
        f"{base}/payments/",
        data=payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert created.status_code == 201
    assert created.json()["unapplied_amount"] == "10.00"

    invalid_amount = client.post(
        f"{base}/payments/",
        data={**payload, "amount": "-0.01"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert invalid_amount.status_code == 400
    assert invalid_amount.json()["error"]["code"] == "invalid_request"

    incompatible_currency = client.post(
        f"{base}/payments/",
        data={**payload, "currency": "EUR"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert incompatible_currency.status_code == 409
    assert incompatible_currency.json()["error"]["code"] == "currency_mismatch"

    cross = client.get(f"/api/v1/organizations/{foreign.organization.pk}/receivables/portfolio/")
    assert cross.status_code == 404

    commercial = User.objects.create_user(
        email="receivables-commercial@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    add_membership(
        organization_id=organization_id,
        user_id=commercial.pk,
        role=Membership.Role.COMMERCIAL,
    )
    commercial_client = Client(enforce_csrf_checks=True)
    _login(commercial_client, commercial)
    summary = commercial_client.get(f"{base}/roots/{reservation['root_id']}/summary/")
    assert summary.status_code == 200
    assert set(summary.json()) >= {"original_total", "applied_total", "balance"}
    assert commercial_client.get(f"{base}/portfolio/").status_code == 403
    Membership.objects.filter(user=commercial, organization_id=organization_id).update(
        status=Membership.Status.SUSPENDED,
        suspended_at=timezone.now(),
    )
    inactive_summary = commercial_client.get(f"{base}/roots/{reservation['root_id']}/summary/")
    assert inactive_summary.status_code == 404
