from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from claridez.commercial import analytics as commercial
from claridez.commercial.analytics_access import AnalyticsScheduleContext
from claridez.commercial.models import EventRequestHistory
from claridez.operations import analytics as operations
from claridez.operations.advanced_models import (
    OperationalChangeDecision,
    OperationalChangeProposal,
    OperationalVerification,
    OperationalVerificationEvent,
    TemplatePhaseDefinition,
)
from claridez.organizations.analytics_contracts import Coverage, TemporalMode
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.scheduling import analytics as scheduling
from tests.test_p15_query import NOW, authorization
from tests.test_p15_sources import _event, _query


def test_commercial_agenda_batch_uses_current_source_owned_context_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AnalyticsScheduleContext((uuid4(),), (uuid4(),))
    resolve = MagicMock(return_value=context)
    load = MagicMock(return_value=scheduling._Batch((), {}, ()))
    monkeypatch.setattr(scheduling, "schedule_context_for_analytics", resolve)
    monkeypatch.setattr(scheduling, "_load", load)
    auth = authorization(Membership.Role.COMMERCIAL)
    queries = tuple(
        _query("scheduling." + name, TemporalMode.STATE_IN_PERIOD)
        for name in (
            "confirmed_event_minutes",
            "confirmed_occupied_minutes",
            "confirmed_reservation_count",
        )
    )
    scheduling.fetch_analytics_metrics(auth, queries)
    resolve.assert_called_once_with(auth)
    load.assert_called_once_with(auth, NOW, context)


@pytest.mark.parametrize("filter_kind", ["absent", "foreign"])
def test_commercial_blocks_require_an_explicit_authorized_space(
    monkeypatch: pytest.MonkeyPatch,
    filter_kind: str,
) -> None:
    context = AnalyticsScheduleContext((uuid4(),), (uuid4(),))
    monkeypatch.setattr(scheduling, "schedule_context_for_analytics", lambda _: context)
    load = MagicMock()
    monkeypatch.setattr(scheduling, "_load", load)
    query = replace(
        _query("scheduling.blocked_minutes", TemporalMode.STATE_IN_PERIOD), dimensions=("space_id",)
    )
    if filter_kind == "foreign":
        query = replace(query, filters=(("space_id", str(uuid4())),))
    with pytest.raises(AuthorizationDenied):
        scheduling.fetch_analytics_metrics(authorization(Membership.Role.COMMERCIAL), (query,))
    load.assert_not_called()


def test_non_commercial_schedule_does_not_infer_a_sales_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve = MagicMock()
    monkeypatch.setattr(scheduling, "schedule_context_for_analytics", resolve)
    monkeypatch.setattr(scheduling, "_load", lambda *_: scheduling._Batch((), {}, ()))
    scheduling.fetch_analytics_metrics(
        authorization(Membership.Role.OPERATIONS),
        (
            replace(
                _query("scheduling.blocked_minutes", TemporalMode.STATE_IN_PERIOD),
                dimensions=("space_id",),
            ),
        ),
    )
    resolve.assert_not_called()


@pytest.mark.parametrize("known", [False, True])
def test_request_person_cohort_uses_creation_identity_never_the_current_person(
    monkeypatch: pytest.MonkeyPatch,
    known: bool,
) -> None:
    person_id = uuid4() if known else None
    row = EventRequestHistory(
        id=uuid4(),
        event_request_id=uuid4(),
        analytics_person_id=person_id,
        kind="created",
        request_revision=1,
        origin="referral",
        occurred_at=NOW - timedelta(days=2),
        created_at=NOW - timedelta(days=2),
    )
    monkeypatch.setattr(commercial, "_history", lambda *_: (row,))
    query = _query("commercial.request_person_cohort", TemporalMode.COHORT)
    result = commercial.request_cohort(authorization(), query)
    assert result.items[0].related_id == person_id
    assert result.coverage is (Coverage.COMPLETE if known else Coverage.UNAVAILABLE)
    # La misma falta de evidencia personal no altera una cohorte de solicitudes.
    request_result = commercial.request_cohort(
        authorization(),
        replace(
            query,
            source_metric_id="commercial.request_created_cohort",
        ),
    )
    assert request_result.coverage is Coverage.COMPLETE


@pytest.mark.parametrize("has_evidence", [False, True])
def test_scheduling_venue_dimension_requires_event_evidence_not_current_space(
    has_evidence: bool,
) -> None:
    event = _event()
    venue_id = uuid4()
    event.analytics_new_venue_id = venue_id if has_evidence else None
    query = replace(
        _query("scheduling.confirmed_reservation_count", TemporalMode.STATE_IN_PERIOD),
        dimensions=("venue_id",),
    )
    result = scheduling._metric(query, scheduling._Batch((event,), {"space": str(uuid4())}, ()))
    if has_evidence:
        assert result.coverage is Coverage.COMPLETE
        assert result.points[0].dimensions == (("venue_id", str(venue_id)),)
    else:
        assert result.coverage is Coverage.UNAVAILABLE
        assert not result.points


@pytest.mark.parametrize("has_change", [False, True])
def test_verification_uses_frozen_definition_and_visible_approved_change(
    monkeypatch: pytest.MonkeyPatch,
    has_change: bool,
) -> None:
    definition = TemplatePhaseDefinition(
        id=uuid4(), phase="setup", role_key="host", is_required=True
    )
    row = OperationalVerification(
        id=uuid4(), definition=definition, is_required=False, role_key="later"
    )
    proposal = OperationalChangeProposal(
        id=uuid4(),
        target_id=row.pk,
        before_payload={"is_required": True, "role_key": "host"},
        proposed_payload={"is_required": False},
    )
    decision = OperationalChangeDecision(id=uuid4(), proposal=proposal, decided_at=NOW)
    verification_rows = MagicMock()
    verification_rows.filter.return_value.select_related.return_value.only.return_value = (row,)
    changes = MagicMock()
    ordered_changes = changes.filter.return_value.select_related.return_value.only.return_value
    ordered_changes.order_by.return_value = (decision,) if has_change else ()
    events = MagicMock()
    events.filter.return_value.only.return_value.order_by.return_value = ()
    monkeypatch.setattr(OperationalVerification, "objects", verification_rows)
    monkeypatch.setattr(OperationalChangeDecision, "objects", changes)
    monkeypatch.setattr(OperationalVerificationEvent, "objects", events)
    query = _query("operations.pending_required_verification_count", TemporalMode.STATE)
    result = operations._verifications(authorization(), query)
    assert result.coverage is Coverage.COMPLETE
    assert result.points[0].value == (0 if has_change else 1)
    assert changes.filter.call_args.kwargs["decided_at__lte"] == query.as_of_at
    assert changes.filter.call_args.kwargs["created_at__lte"] == query.knowledge_cutoff_at
    assert "is_required" not in verification_rows.filter.call_args.kwargs
