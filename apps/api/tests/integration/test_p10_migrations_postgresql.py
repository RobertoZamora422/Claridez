from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

import claridez.commercial.public as commercial_port
import claridez.operations.public as operations_port
import claridez.scheduling.public as scheduling_port
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.models import (
    CollectionScheduleDue,
    LegacyEvidenceReview,
    PaymentApplication,
    ReceivableObligation,
    ReceivedPayment,
)
from claridez.scheduling.models import Reservation, ScheduleEvent
from claridez.scheduling.services import cancel_reservation, reschedule_reservation
from tests.test_receivables import _provisional

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _restore_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _p9_confirm(owner, creation, reservation, *, kind: str):  # type: ignore[no-untyped-def]
    organization_id = creation.organization.pk
    with authorized_tenant_scope(
        owner, organization_id, Capability.RESERVATION_CONFIRM
    ) as authorization:
        readiness = scheduling_port.prepare_confirmation(
            authorization, UUID(str(reservation["id"]))
        )
        confirmed = scheduling_port.confirm_prepared(
            authorization,
            UUID(str(reservation["id"])),
            kind=kind,
            recognized_amount=Decimal("300.00") if kind == "external_deposit" else None,
            reported_at=timezone.now() if kind == "external_deposit" else None,
            reference="LEGACY-5-1" if kind == "external_deposit" else "",
            waiver_reason="Waiver histórico" if kind == "waiver" else "",
        )
        commercial_port.set_request_schedule_status(
            authorization, readiness.reservation.event_request_id, status="confirmed"
        )
        operations_port.initialize_from_accepted_snapshot(
            confirmed.reservation,
            actor_membership_id=authorization.membership_id,
            occurred_at=confirmed.reservation.confirmed_at or timezone.now(),
        )
        return confirmed.data


def _assert_case(owner, organization_id: UUID, **counts: int) -> None:  # type: ignore[no-untyped-def]
    with authorized_tenant_scope(owner, organization_id, Capability.RECEIVABLES_READ):
        assert ReceivableObligation.objects.count() == counts.get("obligations", 0)
        assert ReceivedPayment.objects.count() == counts.get("payments", 0)
        assert PaymentApplication.objects.count() == counts.get("applications", 0)
        assert LegacyEvidenceReview.objects.count() == counts.get("reviews", 0)
        assert CollectionScheduleDue.objects.count() == 0


def test_p9_to_p10_backfill_is_honest_root_scoped_and_reapplicable() -> None:
    try:
        MigrationExecutor(connection).migrate([("receivables", "0001_initial")])

        deposit_owner, deposit_org, _, _, deposit_hold = _provisional("p10-migrate-deposit")
        deposit = _p9_confirm(deposit_owner, deposit_org, deposit_hold, kind="external_deposit")

        waiver_owner, waiver_org, _, _, waiver_hold = _provisional("p10-migrate-waiver")
        _p9_confirm(waiver_owner, waiver_org, waiver_hold, kind="waiver")

        moved_owner, moved_org, _, _, moved_hold = _provisional("p10-migrate-rescheduled")
        moved = _p9_confirm(moved_owner, moved_org, moved_hold, kind="external_deposit")
        successor = reschedule_reservation(
            moved_owner,
            moved_org.organization.pk,
            reservation_id=moved["id"],
            revision=moved["revision"],
            idempotency_key=uuid4(),
            space_id=moved["space_id"],
            starts_at_local=datetime(2026, 11, 20, 18, 0),
            ends_at_local=datetime(2026, 11, 20, 23, 0),
            timezone_name="America/Guayaquil",
            reason="Reprogramación histórica P9",
            commercial_terms_unchanged=True,
        )["reservation"]

        cancelled_owner, cancelled_org, _, _, cancelled_hold = _provisional("p10-migrate-cancelled")
        cancelled = _p9_confirm(
            cancelled_owner, cancelled_org, cancelled_hold, kind="external_deposit"
        )
        cancel_reservation(
            cancelled_owner,
            cancelled_org.organization.pk,
            reservation_id=cancelled["id"],
            reason="Cancelación histórica posterior a confirmar",
        )

        provisional_owner, provisional_org, _, _, _ = _provisional("p10-migrate-provisional")

        _restore_head()

        _assert_case(
            deposit_owner,
            deposit_org.organization.pk,
            obligations=1,
            payments=1,
            applications=1,
        )
        with authorized_tenant_scope(
            deposit_owner, deposit_org.organization.pk, Capability.RECEIVABLES_READ
        ):
            obligation = ReceivableObligation.objects.get()
            payment = ReceivedPayment.objects.get()
            assert obligation.original_total == Decimal("1617.20")
            assert (
                ScheduleEvent.objects.get(pk=obligation.confirmation_event_id).kind
                == "reservation_confirmed"
            )
            assert payment.amount == Decimal("300.00")
            assert payment.provenance == "legacy_5_1_confirmation"
            assert payment.evidence_level == "internal_report"
            assert payment.confirmation_source_id == deposit["id"]

        _assert_case(waiver_owner, waiver_org.organization.pk, obligations=1)
        _assert_case(
            moved_owner,
            moved_org.organization.pk,
            obligations=1,
            payments=1,
            applications=1,
        )
        with authorized_tenant_scope(
            moved_owner, moved_org.organization.pk, Capability.RECEIVABLES_READ
        ):
            obligation = ReceivableObligation.objects.get()
            assert obligation.root_reservation_id == moved_hold["root_id"]
            assert Reservation.objects.filter(root_id=obligation.root_reservation_id).count() == 2
            assert Reservation.objects.get(pk=successor["id"]).confirmation_source_id == moved["id"]

        _assert_case(
            cancelled_owner,
            cancelled_org.organization.pk,
            obligations=1,
            payments=1,
            applications=1,
        )
        _assert_case(provisional_owner, provisional_org.organization.pk)

        MigrationExecutor(connection).migrate([("receivables", None)])
        _restore_head()
        _assert_case(
            deposit_owner,
            deposit_org.organization.pk,
            obligations=1,
            payments=1,
            applications=1,
        )
    finally:
        _restore_head()
