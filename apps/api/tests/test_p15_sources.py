from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from claridez.organizations.analytics_contracts import Coverage, SourceMetricQuery, TemporalMode
from claridez.receivables.analytics import _facts, _Ledger, _state
from claridez.receivables.models import (
    CollectionScheduleDue,
    CollectionScheduleRevision,
    MovementReversal,
    PaymentApplication,
    ReceivableAdjustment,
    ReceivableObligation,
    ReceivedPayment,
    RefundApplication,
    RefundRecord,
)
from claridez.scheduling.analytics import _Batch, _metric
from claridez.scheduling.models import ScheduleEvent

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)
BEFORE = NOW - timedelta(days=2)


def _query(name: str, mode: TemporalMode) -> SourceMetricQuery:
    return SourceMetricQuery(
        name,
        1,
        mode,
        BEFORE - timedelta(days=1) if mode != TemporalMode.STATE else None,
        NOW - timedelta(days=1) if mode != TemporalMode.STATE else None,
        NOW if mode != TemporalMode.FACT else None,
        NOW,
        NOW,
        "America/Guayaquil",
        dimensions=("currency",) if name.startswith("receivables.") else (),
    )


def _ledger() -> _Ledger:
    obligation = ReceivableObligation(
        id=uuid4(), original_total=Decimal("100.00"), confirmed_at=BEFORE, currency="USD"
    )
    payment = ReceivedPayment(
        id=uuid4(),
        amount=Decimal("120.00"),
        reported_at=BEFORE,
        currency="USD",
        method="cash",
        provenance="manual",
    )
    application = PaymentApplication(
        id=uuid4(),
        payment_id=payment.pk,
        obligation_id=obligation.pk,
        amount=Decimal("80.00"),
        currency="USD",
        applied_at=BEFORE,
    )
    refund = RefundRecord(
        id=uuid4(),
        payment_id=payment.pk,
        amount=Decimal("40.00"),
        currency="USD",
        refunded_at=BEFORE,
    )
    allocation = RefundApplication(
        id=uuid4(),
        refund_id=refund.pk,
        payment_application_id=application.pk,
        amount=Decimal("20.00"),
        currency="USD",
    )
    return _Ledger(
        (obligation,), (payment,), (application,), (), (refund,), (allocation,), (), (), (), False
    )


def _value(result: object) -> Decimal | int | None:
    from claridez.organizations.analytics_contracts import SourceMetricResult

    assert isinstance(result, SourceMetricResult)
    assert result.coverage is Coverage.COMPLETE
    return result.points[0].value


def test_receivables_open_balance_and_cohort_unapplied_use_different_equations() -> None:
    ledger = _ledger()
    assert (
        _value(_state(_query("receivables.open_balance_amount", TemporalMode.STATE), ledger)) == 40
    )
    assert (
        _value(_state(_query("receivables.payment_unapplied_amount", TemporalMode.COHORT), ledger))
        == 20
    )


def test_refund_reversal_restores_only_allocated_portion_not_gross_refund() -> None:
    ledger = _ledger()
    reversal = MovementReversal(
        id=uuid4(),
        target_kind="refund",
        target_id=ledger.refunds[0].pk,
        amount=Decimal("40.00"),
        currency="USD",
        reversed_at=BEFORE,
    )
    ledger = replace(ledger, reversals=(reversal,))
    q = _query("receivables.application_net_amount", TemporalMode.FACT)
    q = replace(q, dimensions=("currency", "effect_kind"))
    values = {dict(p.dimensions)["effect_kind"]: p.value for p in _facts(q, ledger).points}
    assert values == {
        "application": Decimal("80"),
        "refund_allocation": Decimal("-20"),
        "refund_reversal": Decimal("20"),
    }
    assert (
        _value(_state(_query("receivables.open_balance_amount", TemporalMode.STATE), ledger)) == 20
    )
    assert (
        _value(_state(_query("receivables.payment_unapplied_amount", TemporalMode.COHORT), ledger))
        == 40
    )


def test_gross_payment_and_refund_do_not_disappear_after_reversal() -> None:
    ledger = _ledger()
    reversal = MovementReversal(
        id=uuid4(),
        target_kind="payment",
        target_id=ledger.payments[0].pk,
        amount=Decimal("120"),
        currency="USD",
        reversed_at=BEFORE,
    )
    ledger = replace(ledger, reversals=(reversal,))
    assert (
        _value(_facts(_query("receivables.payment_received_amount", TemporalMode.FACT), ledger))
        == 120
    )
    assert (
        _value(_facts(_query("receivables.refund_recorded_amount", TemporalMode.FACT), ledger))
        == 40
    )
    assert (
        _value(_state(_query("receivables.payment_unapplied_amount", TemporalMode.COHORT), ledger))
        == 0
    )


def test_adjustment_and_reversal_cancel_by_their_own_economic_times() -> None:
    ledger = _ledger()
    adjustment = ReceivableAdjustment(
        id=uuid4(),
        obligation_id=ledger.obligations[0].pk,
        amount=Decimal("10"),
        direction="decrease",
        currency="USD",
        occurred_at=BEFORE,
    )
    reversal = MovementReversal(
        id=uuid4(),
        target_kind="adjustment",
        target_id=adjustment.pk,
        amount=Decimal("10"),
        currency="USD",
        reversed_at=NOW,
    )
    ledger = replace(ledger, adjustments=(adjustment,), reversals=(reversal,))
    assert (
        _value(_facts(_query("receivables.adjustment_net_amount", TemporalMode.FACT), ledger))
        == -10
    )
    assert (
        _value(_state(_query("receivables.open_balance_amount", TemporalMode.STATE), ledger)) == 40
    )


def test_asof_excludes_later_application_and_later_schedule_revision() -> None:
    ledger = _ledger()
    obligation = ledger.obligations[0]
    first = CollectionScheduleRevision(
        id=uuid4(), obligation_id=obligation.pk, revision=1, published_at=BEFORE
    )
    second = CollectionScheduleRevision(
        id=uuid4(), obligation_id=obligation.pk, revision=2, published_at=NOW + timedelta(days=1)
    )
    due = CollectionScheduleDue(
        id=uuid4(),
        obligation_id=obligation.pk,
        schedule_revision_id=first.pk,
        due_key=uuid4(),
        amount=Decimal("100"),
        currency="USD",
        due_on=BEFORE.date(),
        position=1,
    )
    later_app = PaymentApplication(
        id=uuid4(),
        payment_id=ledger.payments[0].pk,
        obligation_id=obligation.pk,
        amount=Decimal("20"),
        currency="USD",
        applied_at=NOW + timedelta(hours=1),
    )
    ledger = replace(
        ledger,
        applications=(*ledger.applications, later_app),
        revisions=(first, second),
        dues=(due,),
    )
    q = replace(
        _query("receivables.aging_open_balance_amount", TemporalMode.STATE),
        dimensions=("currency", "aging_bucket"),
    )
    result = _state(q, ledger)
    assert _value(result) == 40
    assert dict(result.points[0].dimensions)["aging_bucket"] == "1_30"


def test_currencies_remain_separate() -> None:
    ledger = _ledger()
    eur = ReceivedPayment(
        id=uuid4(),
        currency="EUR",
        amount=Decimal("99"),
        reported_at=BEFORE,
        method="cash",
        provenance="manual",
    )
    ledger = replace(ledger, payments=(*ledger.payments, eur))
    result = _facts(_query("receivables.payment_received_amount", TemporalMode.FACT), ledger)
    assert {dict(p.dimensions)["currency"]: p.value for p in result.points} == {
        "USD": 120,
        "EUR": 99,
    }


def _event(
    *, kind: str = "reservation_confirmed", status: str = "confirmed", root: UUID | None = None
) -> ScheduleEvent:
    return ScheduleEvent(
        id=uuid4(),
        root_reservation_id=root or uuid4(),
        kind=kind,
        occurred_at=BEFORE - timedelta(days=2),
        recorded_at=BEFORE - timedelta(days=1),
        new_snapshot={
            "status": status,
            "space_id": "space",
            "starts_at": BEFORE.isoformat(),
            "ends_at": (BEFORE + timedelta(hours=1)).isoformat(),
            "setup_minutes": 20,
            "teardown_minutes": 10,
            "buffer_before_minutes": 5,
            "buffer_after_minutes": 5,
        },
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("confirmed_event_minutes", 60),
        ("confirmed_occupied_minutes", 100),
        ("confirmed_reservation_count", 1),
    ],
)
def test_scheduling_uses_event_vs_occupied_intervals(name: str, expected: int) -> None:
    batch = _Batch((_event(),), {"space": "venue"}, ())
    assert (
        _value(_metric(_query("scheduling." + name, TemporalMode.STATE_IN_PERIOD), batch))
        == expected
    )


def test_cancelled_and_rescheduled_predecessors_do_not_add_occupancy() -> None:
    first = _event()
    successor = _event(kind="reservation_rescheduled", root=first.root_reservation_id)
    successor.occurred_at += timedelta(hours=1)
    cancelled = _event(
        kind="reservation_cancelled", status="cancelled", root=first.root_reservation_id
    )
    cancelled.occurred_at += timedelta(hours=2)
    q = _query("scheduling.confirmed_reservation_count", TemporalMode.STATE_IN_PERIOD)
    assert _value(_metric(q, _Batch((first, successor), {"space": "venue"}, ()))) == 1
    assert _value(_metric(q, _Batch((first, successor, cancelled), {"space": "venue"}, ()))) == 0


def test_non_intersecting_reservation_count_is_zero() -> None:
    event = _event()
    q = replace(
        _query("scheduling.confirmed_reservation_count", TemporalMode.STATE_IN_PERIOD),
        period_start=NOW + timedelta(days=3),
        period_end=NOW + timedelta(days=4),
    )
    assert _value(_metric(q, _Batch((event,), {"space": "venue"}, ()))) == 0
