"""Concurrencia y guardianes PostgreSQL reales de Resources P12."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction

from claridez.application.resources_finance import materialize_resources_receipt
from claridez.finance.models import (
    ActualDirectCost,
    ExpenseOccurrence,
    FinanceCategory,
    FinancialSourceReference,
)
from claridez.finance.services import create_category, create_period
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.resources.errors import ResourcesError
from claridez.resources.models import (
    Resource,
    ResourceAssignment,
    ResourceCapacityAllocation,
    SerializedAsset,
)
from claridez.resources.services import create_requirement, reserve_resource
from tests.test_receivables import _confirmed
from tests.test_resources import _resource_in_organization, _temporal_holds

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _reserve_worker(
    actor_id: UUID,
    organization_id: UUID,
    requirement_id: UUID,
    location_id: UUID | None,
    asset_id: UUID | None,
    barrier: Barrier,
) -> str:
    close_old_connections()
    try:
        actor = User.objects.get(pk=actor_id)
        barrier.wait(timeout=10)
        reserve_resource(
            actor,
            organization_id,
            requirement_id=requirement_id,
            source_location_id=location_id,
            serialized_asset_id=asset_id,
            idempotency_key=uuid4(),
        )
        return "ok"
    except (ResourcesError, IntegrityError):
        return "conflict"
    finally:
        close_old_connections()


@pytest.mark.parametrize(
    ("nature", "slug", "declared_capacity"),
    [
        (Resource.Nature.CONSUMABLE, "consumable", None),
        (Resource.Nature.REUSABLE_POOL, "pool", None),
        (Resource.Nature.SERIALIZED_ASSET, "asset", None),
        (Resource.Nature.SUPPLIED_SERVICE, "service", "1"),
    ],
    ids=("consumable", "reusable-pool", "serialized-asset", "supplied-service"),
)
def test_each_resource_nature_allows_only_one_concurrent_capacity_winner(
    nature: str, slug: str, declared_capacity: str | None
) -> None:
    owner, creation, _, _, _, confirmed = _confirmed(f"p12-race-{slug}")
    organization_id = creation.organization.pk
    resource, location, _ = _resource_in_organization(
        owner,
        organization_id,
        f"race-{slug}",
        nature,
        quantity="1",
        declared_capacity=declared_capacity,
    )
    asset_id = None
    if nature == Resource.Nature.SERIALIZED_ASSET:
        with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
            asset_id = SerializedAsset.objects.get(resource=resource).pk
    requirements = tuple(
        create_requirement(
            owner,
            organization_id,
            reservation_id=confirmed["id"],
            resource_id=resource.pk,
            quantity="1",
            reason=f"Carrera {position}",
            idempotency_key=uuid4(),
        )
        for position in range(2)
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _reserve_worker,
                owner.pk,
                organization_id,
                requirement.pk,
                None if location is None else location.pk,
                asset_id,
                barrier,
            )
            for requirement in requirements
        ]
        results = [future.result(timeout=20) for future in futures]
    assert results.count("ok") == 1
    assert results.count("conflict") == 1


@pytest.mark.parametrize(
    "nature",
    (Resource.Nature.REUSABLE_POOL, Resource.Nature.SERIALIZED_ASSET),
    ids=("reusable-pool", "serialized-asset"),
)
def test_postgresql_guards_allow_disjoint_capacity_and_reject_direct_overlap(
    nature: str,
) -> None:
    owner, organization_id, _, holds = _temporal_holds(f"p12-pg-{nature}")
    resource, location, _ = _resource_in_organization(
        owner,
        organization_id,
        f"pg-{nature}",
        nature,
        quantity="1",
    )
    assert location is not None
    asset = None
    if nature == Resource.Nature.SERIALIZED_ASSET:
        with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
            asset = SerializedAsset.objects.get(resource=resource)
    for hold in holds[:2]:
        requirement = create_requirement(
            owner,
            organization_id,
            reservation_id=hold["id"],
            resource_id=resource.pk,
            quantity="1",
            reason="Prueba PostgreSQL no solapada",
            idempotency_key=uuid4(),
        )
        reserve_resource(
            owner,
            organization_id,
            requirement_id=requirement.pk,
            source_location_id=location.pk,
            serialized_asset_id=None if asset is None else asset.pk,
            idempotency_key=uuid4(),
        )
    overlap = create_requirement(
        owner,
        organization_id,
        reservation_id=holds[2]["id"],
        resource_id=resource.pk,
        quantity="1",
        reason="Inserción directa solapada",
        idempotency_key=uuid4(),
    )
    with (
        pytest.raises(IntegrityError),
        authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_RESERVE) as auth,
        transaction.atomic(),
    ):
        assignment = ResourceAssignment.objects.create(
            organization_id=organization_id,
            requirement=overlap,
            root_reservation_id=overlap.root_reservation_id,
            reservation_id=overlap.reservation_id,
            resource=resource,
            serialized_asset=asset,
            source_location=location,
            quantity=overlap.quantity,
            resource_interval=overlap.resource_interval,
            recorded_by_membership_id=auth.membership_id,
        )
        ResourceCapacityAllocation.objects.create(
            organization_id=organization_id,
            assignment=assignment,
            reservation_id=assignment.reservation_id,
            resource=resource,
            serialized_asset=asset,
            quantity=assignment.quantity,
            resource_interval=assignment.resource_interval,
        )


def test_orm_bulk_cannot_invent_serialized_physical_custody() -> None:
    owner, creation, _, _, _, _ = _confirmed("p12-pg-asset-bulk")
    organization_id = creation.organization.pk
    resource, _, _ = _resource_in_organization(
        owner,
        organization_id,
        "pg-asset-bulk",
        Resource.Nature.SERIALIZED_ASSET,
        quantity="1",
    )
    with (
        pytest.raises(IntegrityError),
        authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_MAINTAIN),
        transaction.atomic(),
    ):
        SerializedAsset.objects.filter(resource=resource).update(
            status=SerializedAsset.Status.CUSTODY
        )


def test_resources_tables_force_rls_and_ledgers_have_minimum_app_privileges() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relname LIKE 'resources_%' "
            "AND relkind IN ('r', 'p')"
        )
        rows = cursor.fetchall()
        assert rows
        assert all(row[1] and row[2] for row in rows)
        cursor.execute(
            "SELECT "
            "has_table_privilege('claridez_app', 'resources_stockmovement', 'SELECT'), "
            "has_table_privilege('claridez_app', 'resources_stockmovement', 'INSERT'), "
            "has_table_privilege('claridez_app', 'resources_stockmovement', 'UPDATE'), "
            "has_table_privilege('claridez_app', 'resources_stockmovement', 'DELETE'), "
            "has_table_privilege('claridez_app', 'resources_stockmovement', 'TRUNCATE'), "
            "has_table_privilege('claridez_app', 'resources_stockbalance', 'UPDATE'), "
            "has_table_privilege('claridez_app', 'finance_financialsourcereference', 'DELETE')"
        )
        assert cursor.fetchone() == (True, True, False, False, False, True, False)
        cursor.execute(
            "SELECT confrelid = 'resources_supplyreceiptline'::regclass "
            "FROM pg_constraint WHERE conname = 'finance_source_receiptline_fk'"
        )
        assert cursor.fetchone() == (True,)


def _finance_worker(
    actor_id: UUID,
    organization_id: UUID,
    receipt_line_id: UUID,
    target_kind: str,
    category_id: UUID,
    root_reservation_id: UUID,
    venue_id: UUID,
    barrier: Barrier,
) -> str:
    close_old_connections()
    try:
        actor = User.objects.get(pk=actor_id)
        barrier.wait(timeout=10)
        materialize_resources_receipt(
            actor,
            organization_id,
            receipt_line_id=receipt_line_id,
            target_kind=target_kind,
            category_id=category_id,
            amount=Decimal("25.00"),
            currency="USD",
            economic_date=date.today(),
            description="Carrera de procedencia P12",
            evidence_reference="P12-RACE",
            root_reservation_id=(
                root_reservation_id if target_kind == "actual_direct_cost" else None
            ),
            venue_id=venue_id if target_kind == "actual_direct_cost" else None,
            expense_type="variable" if target_kind == "expense_occurrence" else None,
            allocations=(
                (
                    {
                        "scope": "business",
                        "root_reservation_id": None,
                        "venue_id": None,
                        "amount": Decimal("25.00"),
                    },
                )
                if target_kind == "expense_occurrence"
                else ()
            ),
            idempotency_key=uuid4(),
        )
        return "ok"
    except (ResourcesError, IntegrityError):
        return "conflict"
    finally:
        close_old_connections()


def test_resources_receipt_finance_materialization_has_one_concurrent_winner() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("p12-finance-race")
    organization_id = creation.organization.pk
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    _, _, receipt = _resource_in_organization(
        owner,
        organization_id,
        "finance-race",
        Resource.Nature.SUPPLIED_SERVICE,
        quantity="1",
        declared_capacity="1",
        root_reservation_id=UUID(str(confirmed["root_id"])),
        venue_id=venue_id,
    )
    starts_on = date.today().replace(day=1)
    ends_on = (
        date(starts_on.year + 1, 1, 1)
        if starts_on.month == 12
        else date(starts_on.year, starts_on.month + 1, 1)
    )
    create_period(
        owner,
        organization_id,
        starts_on=starts_on,
        ends_on=ends_on,
        label="Carrera P12",
        idempotency_key=uuid4(),
    )
    direct_category = create_category(
        owner,
        organization_id,
        kind=FinanceCategory.Kind.DIRECT_COST,
        name="Costo carrera P12",
        idempotency_key=uuid4(),
    )
    expense_category = create_category(
        owner,
        organization_id,
        kind=FinanceCategory.Kind.VARIABLE_EXPENSE,
        name="Gasto carrera P12",
        idempotency_key=uuid4(),
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=30)
            for future in (
                executor.submit(
                    _finance_worker,
                    owner.pk,
                    organization_id,
                    receipt.pk,
                    "actual_direct_cost",
                    direct_category.pk,
                    UUID(str(confirmed["root_id"])),
                    venue_id,
                    barrier,
                ),
                executor.submit(
                    _finance_worker,
                    owner.pk,
                    organization_id,
                    receipt.pk,
                    "expense_occurrence",
                    expense_category.pk,
                    UUID(str(confirmed["root_id"])),
                    venue_id,
                    barrier,
                ),
            )
        ]
    assert results.count("ok") == 1
    assert results.count("conflict") == 1
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        assert FinancialSourceReference.objects.filter(source_id=receipt.pk).count() == 1
        assert (
            ActualDirectCost.objects.filter(provenance="resources_receipt").count()
            + ExpenseOccurrence.objects.filter(provenance="resources_receipt").count()
            == 1
        )
