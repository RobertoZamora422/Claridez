"""Dataset sintético P15: usa comandos fuente reales, nunca fabrica historia ni desactiva RLS.

Solo se importa desde pytest. El perfil representativo no se confunde con el pequeño de smoke.
Las fechas económicas dependen del ancla de ejecución, los conteos y proporciones son estables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from django.utils import timezone

from claridez.analytics.query import MetricSelection
from claridez.analytics.registry import METRICS
from claridez.application.reservation_confirmation import confirm_reservation
from claridez.catalog.services import create_event_type
from claridez.commercial.services import create_event_request, create_person
from claridez.crm.services import create_task, record_interaction
from claridez.finance.services import (
    create_category,
    publish_direct_cost_plan,
    record_actual_direct_cost,
    record_cash_movement,
    record_expense,
)
from claridez.identity.models import User
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.models import Membership
from claridez.resources.models import Resource
from claridez.resources.services import create_requirement, record_movement, reserve_resource
from tests.test_finance import _complete, _make_period
from tests.test_p8_scheduling import _owner
from tests.test_receivables import _accepted
from tests.test_resources import _resource_in_organization


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    name: str
    requests: int
    resources: int
    extra_movements_per_resource: int

    def __post_init__(self) -> None:
        if self.requests < 16 or self.requests % 16 or self.resources < 1:
            raise ValueError("dataset_profile_requires_whole_cohorts")

    @property
    def expected(self) -> dict[str, int]:
        return {
            "people": (self.requests + 9) // 10,
            "requests": self.requests,
            "interactions": self.requests,
            "tasks": self.requests // 2,
            "issued_quotes": self.requests // 4,
            "accepted_quotes": self.requests // 4,
            "confirmed_roots": self.requests // 8,
            "preparations": self.requests // 8,
            "execution_completed": self.requests // 16,
            "payments": self.requests // 8,
            "applications": self.requests // 8,
            "obligations": self.requests // 8,
            "finance_periods": 1,
            "cost_plans": self.requests // 8,
            "direct_costs": self.requests // 8,
            "variable_expenses": self.requests // 8,
            "cash_outflows": self.requests // 8,
            "resources": self.resources,
            "receipts": self.resources,
            "stock_movements": self.resources * (1 + self.extra_movements_per_resource),
            "requirements": self.requests // 8,
            "assignments": self.requests // 8,
        }


SMOKE = DatasetProfile("p15-smoke-v1", 16, 2, 2)
REPRESENTATIVE = DatasetProfile("p15-representative-v1", 2400, 24, 32)


@dataclass(frozen=True, slots=True)
class Dataset:
    actor: User
    commercial_actor: User
    organization_id: UUID
    profile: DatasetProfile
    period_id: UUID
    recorded_start: datetime
    recorded_end: datetime
    interval_start: datetime
    interval_end: datetime

    def selections(self) -> tuple[MetricSelection, ...]:
        asof = timezone.now()
        return tuple(
            MetricSelection(
                row.metric_id,
                dimensions=row.required_dimensions,
                period_start=(
                    self.interval_start
                    if row.temporal_mode.value == "SI"
                    else self.recorded_start
                    if row.temporal_mode.value in {"F", "C"}
                    else None
                ),
                period_end=(
                    self.interval_end
                    if row.temporal_mode.value == "SI"
                    else self.recorded_end
                    if row.temporal_mode.value in {"F", "C"}
                    else None
                ),
                as_of_at=None if row.temporal_mode.value == "F" else asof,
                operational_period_id=self.period_id if row.temporal_mode.value == "FP" else None,
            )
            for row in METRICS
        )


def build_dataset(slug: str, profile: DatasetProfile = SMOKE) -> Dataset:
    """Datos de prueba mediante servicios; sin SQL de inserción ni backdating del registro."""
    recorded_start = timezone.now() - timedelta(seconds=1)
    actor, oid = _owner(slug)
    commercial_actor = User.objects.create_user(
        email=f"{slug}-commercial@example.test",
        password=None,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    commercial_membership = Membership.objects.create(
        organization_id=oid,
        user=commercial_actor,
        role=Membership.Role.COMMERCIAL,
        status=Membership.Status.ACTIVE,
    )
    venue = list_venues(actor, oid)[0]
    venue_id, space_id = UUID(str(venue["id"])), UUID(str(venue["spaces"][0]["id"]))
    event_type = create_event_type(actor, oid, name="Evento sintético P15")
    economic_date = timezone.localdate()
    period = _make_period(actor, oid, economic_date, "Periodo sintético P15")
    cost_category = create_category(
        actor, oid, kind="direct_cost", name="Costo sintético", idempotency_key=uuid4()
    )
    expense_category = create_category(
        actor, oid, kind="variable_expense", name="Gasto sintético", idempotency_key=uuid4()
    )
    resources = [
        _resource_in_organization(
            actor, oid, f"p15-{index}", Resource.Nature.REUSABLE_POOL, quantity="10000"
        )[:2]
        for index in range(profile.resources)
    ]
    for resource, location in resources:
        assert location is not None
        for index in range(profile.extra_movements_per_resource):
            record_movement(
                actor,
                oid,
                resource_id=resource.pk,
                location_id=location.pk,
                kind="adjustment",
                quantity="1",
                direction="increase" if index % 2 == 0 else "decrease",
                reason="Movimiento sintético P15",
                other_location_id=None,
                corrects_id=None,
                idempotency_key=uuid4(),
            )
    start = timezone.now() + timedelta(days=2)
    person_id: UUID | None = None
    for index in range(profile.requests):
        if index % 10 == 0:
            person = create_person(
                actor,
                oid,
                full_name=f"Persona sintética {index // 10}",
                phone=f"09{index // 10:08d}",
                email=None,
                origin="referral",
                origin_detail=None,
            )
            person_id = UUID(str(person["id"]))
        assert person_id is not None
        event_start = start + timedelta(hours=index * 6)
        request = create_event_request(
            actor,
            oid,
            person_id=person_id,
            event_type_id=event_type["id"],
            space_id=space_id,
            starts_at=event_start,
            ends_at=event_start + timedelta(hours=5),
            estimated_guests=100,
            general_need="Dataset sintético P15",
            notes="",
            origin="referral",
            origin_detail=None,
            responsible_membership_id=commercial_membership.pk,
        )
        record_interaction(
            actor,
            oid,
            person_id=person_id,
            event_request_id=request["id"],
            channel="phone_call",
            direction="outbound",
            occurred_at=timezone.now(),
            summary="Respuesta sintética",
        )
        if index % 2 == 0:
            create_task(
                actor,
                oid,
                person_id=person_id,
                event_request_id=request["id"],
                title="Seguimiento sintético",
                due_at=event_start,
                next_contact_at=None,
            )
        if index % 4:
            continue
        _, hold = _accepted(actor, oid, request["id"])
        if index % 8:
            continue
        confirmed = confirm_reservation(
            actor,
            oid,
            reservation_id=hold["id"],
            kind="external_deposit",
            recognized_amount=Decimal("300.00"),
            reported_at=timezone.now(),
            reference=f"SYN-P15-{index}",
            payment_method="bank_transfer",
            idempotency_key=uuid4(),
        )
        root_id = UUID(str(hold["root_id"]))
        publish_direct_cost_plan(
            actor,
            oid,
            root_reservation_id=root_id,
            venue_id=venue_id,
            currency_value="USD",
            reason="Baseline sintética",
            lines=[{"category_id": cost_category.pk, "amount": "100.00"}],
            idempotency_key=uuid4(),
        )
        cost = record_actual_direct_cost(
            actor,
            oid,
            root_reservation_id=root_id,
            venue_id=venue_id,
            category_id=cost_category.pk,
            amount_value="120.00",
            currency_value="USD",
            economic_date=economic_date,
            description="Costo sintético",
            evidence_reference=f"SYN-COST-{index}",
            idempotency_key=uuid4(),
        )
        record_expense(
            actor,
            oid,
            category_id=expense_category.pk,
            expense_type="variable",
            amount_value="20.00",
            currency_value="USD",
            economic_date=economic_date,
            description="Gasto sintético",
            evidence_reference=f"SYN-EXP-{index}",
            allocations=[
                {
                    "scope": "event",
                    "root_reservation_id": root_id,
                    "venue_id": venue_id,
                    "amount": "20.00",
                }
            ],
            idempotency_key=uuid4(),
        )
        record_cash_movement(
            actor,
            oid,
            direction="outflow",
            source_kind="direct_cost",
            source_id=cost.pk,
            original_outflow_id=None,
            amount_value="80.00",
            expense_attributions=[],
            economic_date=economic_date,
            reason="Salida sintética",
            evidence_reference=f"SYN-CASH-{index}",
            idempotency_key=uuid4(),
        )
        resource, location = resources[(index // 8) % profile.resources]
        assert location is not None
        requirement = create_requirement(
            actor,
            oid,
            reservation_id=confirmed["id"],
            resource_id=resource.pk,
            quantity="2",
            reason="Requisito sintético",
            idempotency_key=uuid4(),
        )
        reserve_resource(
            actor,
            oid,
            requirement_id=requirement.pk,
            source_location_id=location.pk,
            serialized_asset_id=None,
            idempotency_key=uuid4(),
        )
        if index % 16 == 0:
            _complete(actor, oid, confirmed["id"])
    return Dataset(
        actor,
        commercial_actor,
        oid,
        profile,
        period.pk,
        recorded_start,
        timezone.now(),
        start - timedelta(days=1),
        start + timedelta(hours=profile.requests * 6, days=1),
    )
