from __future__ import annotations

import ast
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypedDict, overload
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from claridez.application.resources_finance import materialize_resources_receipt
from claridez.application.resources_scheduling import reschedule_with_resources
from claridez.commercial.services import create_person
from claridez.finance.models import (
    ActualDirectCost,
    ExpenseOccurrence,
    FinanceCategory,
    FinancialSourceReference,
    OperatingCashMovement,
)
from claridez.finance.services import create_category, create_period
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.exceptions import TenantAccessDenied
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.resources.errors import ResourcesError
from claridez.resources.models import (
    InventoryLocation,
    MaintenanceRecord,
    PurchaseLine,
    Resource,
    ResourceAssignment,
    ResourceCapacityAllocation,
    ResourceRequirement,
    SerializedAsset,
    StockBalance,
    StockMovement,
    Supplier,
    SupplyReceiptLine,
)
from claridez.resources.services import (
    close_unavailability,
    confirm_receipt_line,
    create_conversion,
    create_location,
    create_purchase,
    create_requirement,
    create_resource,
    create_supplier,
    create_unit,
    execute_assignment,
    link_supplier_contact,
    record_movement,
    record_unavailability,
    reserve_resource,
    resources_overview,
)
from claridez.scheduling.models import Reservation
from claridez.scheduling.services import cancel_reservation, expire_overdue_for_organization
from tests.test_p8_scheduling import PASSWORD as P8_PASSWORD
from tests.test_p8_scheduling import _authenticated_client, _owner
from tests.test_receivables import _confirmed, _provisional


class _MaterializeCommand(TypedDict):
    receipt_line_id: UUID
    target_kind: str
    category_id: UUID
    amount: Decimal
    currency: str
    economic_date: date
    description: str
    evidence_reference: str
    root_reservation_id: UUID | None
    venue_id: UUID | None
    expense_type: str | None
    allocations: tuple[dict[str, object], ...]
    idempotency_key: UUID


def test_resources_domain_imports_other_domains_only_through_public_ports() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "claridez" / "resources"
    violations: list[str] = []
    for module in (package / "services.py", package / "public.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for name in imported:
                if name.startswith(
                    (
                        "claridez.catalog",
                        "claridez.finance",
                        "claridez.operations",
                        "claridez.people",
                        "claridez.scheduling",
                        "claridez.organizations",
                    )
                ) and name not in {
                    "claridez.people.public",
                    "claridez.scheduling.public",
                    "claridez.organizations.public",
                    "claridez.organizations.capabilities",
                    "claridez.organizations.tenant_scope",
                }:
                    violations.append(f"{module.name}: {name}")
    assert violations == []


def _physical_context(
    slug: str, nature: str = Resource.Nature.CONSUMABLE
) -> tuple[User, UUID, Resource, InventoryLocation, Supplier, PurchaseLine]:
    owner, organization_id = _owner(slug)
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    unit = create_unit(
        owner,
        organization_id,
        code=f"u-{slug}",
        name="Unidad",
        symbol="u",
        dimension="count",
        idempotency_key=uuid4(),
    )
    resource = create_resource(
        owner,
        organization_id,
        name=f"Recurso {slug}",
        nature=nature,
        base_unit_id=unit.pk,
        declared_capacity=None,
        idempotency_key=uuid4(),
    )
    location = create_location(
        owner,
        organization_id,
        venue_id=venue_id,
        code=f"B-{slug}",
        name="Bodega",
        idempotency_key=uuid4(),
    )
    supplier = create_supplier(
        owner,
        organization_id,
        legal_name=f"Proveedor {slug}",
        tax_identifier=f"179{abs(hash(slug)) % 100000000:08d}",
        idempotency_key=uuid4(),
    )
    purchase = create_purchase(
        owner,
        organization_id,
        supplier_id=supplier.pk,
        reference=f"OC-{slug}",
        ordered_on=date.today(),
        notes="",
        lines=[
            {
                "resource_id": resource.pk,
                "quantity": "20",
                "description": "Abastecimiento",
            }
        ],
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.PURCHASE_READ):
        line = PurchaseLine.objects.get(purchase=purchase)
    return owner, organization_id, resource, location, supplier, line


@overload
def _resource_in_organization(
    owner: User,
    organization_id: UUID,
    slug: str,
    nature: Literal[Resource.Nature.SUPPLIED_SERVICE],
    *,
    quantity: str = "4",
    declared_capacity: str | None = None,
    root_reservation_id: UUID | None = None,
    venue_id: UUID | None = None,
) -> tuple[Resource, None, SupplyReceiptLine]: ...


@overload
def _resource_in_organization(
    owner: User,
    organization_id: UUID,
    slug: str,
    nature: Literal[
        Resource.Nature.CONSUMABLE,
        Resource.Nature.REUSABLE_POOL,
        Resource.Nature.SERIALIZED_ASSET,
    ],
    *,
    quantity: str = "4",
    declared_capacity: str | None = None,
    root_reservation_id: UUID | None = None,
    venue_id: UUID | None = None,
) -> tuple[Resource, InventoryLocation, SupplyReceiptLine]: ...


@overload
def _resource_in_organization(
    owner: User,
    organization_id: UUID,
    slug: str,
    nature: str,
    *,
    quantity: str = "4",
    declared_capacity: str | None = None,
    root_reservation_id: UUID | None = None,
    venue_id: UUID | None = None,
) -> tuple[Resource, InventoryLocation | None, SupplyReceiptLine]: ...


def _resource_in_organization(
    owner: User,
    organization_id: UUID,
    slug: str,
    nature: str,
    *,
    quantity: str = "4",
    declared_capacity: str | None = None,
    root_reservation_id: UUID | None = None,
    venue_id: UUID | None = None,
) -> tuple[Resource, InventoryLocation | None, SupplyReceiptLine]:
    storage_venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    unit = create_unit(
        owner,
        organization_id,
        code=f"u-{slug}",
        name="Unidad",
        symbol="u",
        dimension="duration" if nature == Resource.Nature.SUPPLIED_SERVICE else "count",
        idempotency_key=uuid4(),
    )
    resource = create_resource(
        owner,
        organization_id,
        name=f"Recurso {slug}",
        nature=nature,
        base_unit_id=unit.pk,
        declared_capacity=declared_capacity,
        idempotency_key=uuid4(),
    )
    location = None
    if nature != Resource.Nature.SUPPLIED_SERVICE:
        location = create_location(
            owner,
            organization_id,
            venue_id=storage_venue_id,
            code=f"L-{slug}",
            name="Bodega",
            idempotency_key=uuid4(),
        )
    supplier = create_supplier(
        owner,
        organization_id,
        legal_name=f"Proveedor {slug}",
        tax_identifier=None,
        internal_code=f"SUP-{slug}",
        idempotency_key=uuid4(),
    )
    purchase = create_purchase(
        owner,
        organization_id,
        supplier_id=supplier.pk,
        reference=f"PO-{slug}",
        ordered_on=date.today(),
        root_reservation_id=root_reservation_id,
        venue_id=venue_id,
        notes="",
        lines=[{"resource_id": resource.pk, "quantity": quantity, "description": "P12"}],
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.PURCHASE_READ):
        line = PurchaseLine.objects.get(purchase=purchase)
    receipt = confirm_receipt_line(
        owner,
        organization_id,
        purchase_line_id=line.pk,
        receipt_reference=f"REC-{slug}",
        received_on=date.today(),
        kind=(
            "service_fulfilled" if nature == Resource.Nature.SUPPLIED_SERVICE else "goods_received"
        ),
        quantity=quantity,
        destination_location_id=None if location is None else location.pk,
        serial_numbers=(
            [f"SN-{slug}-{position}" for position in range(int(quantity))]
            if nature == Resource.Nature.SERIALIZED_ASSET
            else []
        ),
        notes="",
        idempotency_key=uuid4(),
    )
    return resource, location, receipt


@pytest.mark.django_db(transaction=True)
def test_supplier_identity_contact_and_unit_compatibility_are_tenant_aware() -> None:
    owner, organization_id, _, _, supplier, _ = _physical_context("identity")
    person = create_person(
        owner,
        organization_id,
        full_name="Contacto Canónico",
        phone="0991234567",
        email="supplier-contact@example.test",
        origin="referral",
        origin_detail=None,
    )
    contact = link_supplier_contact(
        owner,
        organization_id,
        supplier_id=supplier.pk,
        person_id=person["id"],
        responsibility="Compras",
        is_primary=True,
        idempotency_key=uuid4(),
    )
    assert contact.person_id == UUID(str(person["id"]))

    with pytest.raises(IntegrityError), transaction.atomic():
        create_supplier(
            owner,
            organization_id,
            legal_name="Nombre distinto",
            tax_identifier=supplier.tax_identifier,
            idempotency_key=uuid4(),
        )

    mass = create_unit(
        owner,
        organization_id,
        code="kg",
        name="Kilogramo",
        symbol="kg",
        dimension="mass",
        idempotency_key=uuid4(),
    )
    count = create_unit(
        owner,
        organization_id,
        code="dozen",
        name="Docena",
        symbol="doc",
        dimension="count",
        idempotency_key=uuid4(),
    )
    with pytest.raises(ResourcesError):
        create_conversion(
            owner,
            organization_id,
            from_unit_id=mass.pk,
            to_unit_id=count.pk,
            multiplier="12",
            idempotency_key=uuid4(),
        )


@pytest.mark.django_db(transaction=True)
def test_goods_receipt_is_one_entry_service_has_no_stock_and_serials_square() -> None:
    owner, organization_id, resource, location, _, line = _physical_context("receipt")
    key = uuid4()
    received = confirm_receipt_line(
        owner,
        organization_id,
        purchase_line_id=line.pk,
        receipt_reference="REC-1",
        received_on=date.today(),
        kind="goods_received",
        quantity="8",
        destination_location_id=location.pk,
        serial_numbers=[],
        notes="",
        idempotency_key=key,
    )
    replay = confirm_receipt_line(
        owner,
        organization_id,
        purchase_line_id=line.pk,
        receipt_reference="REC-1",
        received_on=date.today(),
        kind="goods_received",
        quantity="8",
        destination_location_id=location.pk,
        serial_numbers=[],
        notes="",
        idempotency_key=key,
    )
    assert replay.pk == received.pk
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        movement = StockMovement.objects.get(source_id=received.pk)
        assert movement.kind == StockMovement.Kind.ENTRY
        assert movement.quantity == Decimal("8.000000")
        assert StockBalance.objects.get(resource=resource, location=location).quantity == Decimal(
            "8.000000"
        )
    with pytest.raises(ResourcesError) as changed:
        confirm_receipt_line(
            owner,
            organization_id,
            purchase_line_id=line.pk,
            receipt_reference="REC-1",
            received_on=date.today(),
            kind="goods_received",
            quantity="9",
            destination_location_id=location.pk,
            serial_numbers=[],
            notes="",
            idempotency_key=key,
        )
    assert changed.value.code == "idempotency_conflict"

    service_owner, service_org, service, _, _, service_line = _physical_context(
        "service", Resource.Nature.SUPPLIED_SERVICE
    )
    fulfilled = confirm_receipt_line(
        service_owner,
        service_org,
        purchase_line_id=service_line.pk,
        receipt_reference="REC-SERVICE",
        received_on=date.today(),
        kind="service_fulfilled",
        quantity="2",
        destination_location_id=None,
        serial_numbers=[],
        notes="",
        idempotency_key=uuid4(),
    )
    assert fulfilled.resource_id == service.pk
    with authorized_tenant_scope(service_owner, service_org, Capability.RESOURCE_READ):
        assert not StockMovement.objects.filter(organization_id=service_org).exists()

    asset_owner, asset_org, asset_resource, asset_location, _, asset_line = _physical_context(
        "asset", Resource.Nature.SERIALIZED_ASSET
    )
    asset_receipt = confirm_receipt_line(
        asset_owner,
        asset_org,
        purchase_line_id=asset_line.pk,
        receipt_reference="REC-ASSET",
        received_on=date.today(),
        kind="goods_received",
        quantity="2",
        destination_location_id=asset_location.pk,
        serial_numbers=["SER-001", "SER-002"],
        notes="",
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(asset_owner, asset_org, Capability.RESOURCE_READ):
        assert SerializedAsset.objects.filter(receipt_line=asset_receipt).count() == 2
        assert StockBalance.objects.get(resource=asset_resource).quantity == Decimal("2.000000")


@pytest.mark.django_db(transaction=True)
def test_movement_ledger_transfer_return_correction_and_no_negative_balance() -> None:
    owner, organization_id, resource, location, _, line = _physical_context("ledger")
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    target = create_location(
        owner,
        organization_id,
        venue_id=venue_id,
        code="B-DEST",
        name="Destino",
        idempotency_key=uuid4(),
    )
    confirm_receipt_line(
        owner,
        organization_id,
        purchase_line_id=line.pk,
        receipt_reference="REC-LEDGER",
        received_on=date.today(),
        kind="goods_received",
        quantity="10",
        destination_location_id=location.pk,
        serial_numbers=[],
        notes="",
        idempotency_key=uuid4(),
    )
    transfer = record_movement(
        owner,
        organization_id,
        resource_id=resource.pk,
        location_id=location.pk,
        kind="transfer",
        quantity="3",
        direction=None,
        reason="Traslado operativo",
        other_location_id=target.pk,
        corrects_id=None,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        assert StockMovement.objects.filter(transfer_group=transfer.transfer_group).count() == 2
    returned = record_movement(
        owner,
        organization_id,
        resource_id=resource.pk,
        location_id=location.pk,
        kind="return",
        quantity="1",
        direction=None,
        reason="Devolución",
        other_location_id=None,
        corrects_id=None,
        idempotency_key=uuid4(),
    )
    correction = record_movement(
        owner,
        organization_id,
        resource_id=resource.pk,
        location_id=location.pk,
        kind="correction",
        quantity="1",
        direction="decrease",
        reason="Corrección compensatoria",
        other_location_id=None,
        corrects_id=returned.pk,
        idempotency_key=uuid4(),
    )
    assert correction.corrects_id == returned.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        record_movement(
            owner,
            organization_id,
            resource_id=resource.pk,
            location_id=location.pk,
            kind="exit",
            quantity="100",
            direction=None,
            reason="Imposible",
            other_location_id=None,
            corrects_id=None,
            idempotency_key=uuid4(),
        )


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_overview_and_exact_role_matrix() -> None:
    owner_a, organization_a, resource, _, _, _ = _physical_context("tenant-a")
    owner_b, organization_b = _owner("tenant-b")
    overview = resources_overview(owner_a, organization_a)
    resource_rows = overview["resources"]
    assert isinstance(resource_rows, list)
    assert isinstance(resource_rows[0], dict)
    assert resource_rows[0]["id"] == resource.pk
    with pytest.raises(TenantAccessDenied):
        resources_overview(owner_b, organization_a)

    assert Capability.PERSON_MANAGE not in capabilities_for_role(Membership.Role.OPERATIONS)
    assert Capability.PERSON_MANAGE not in capabilities_for_role(Membership.Role.FINANCE)
    assert Capability.SUPPLIER_LINK_CONTACT in capabilities_for_role(Membership.Role.OPERATIONS)
    assert Capability.SUPPLIER_LINK_CONTACT in capabilities_for_role(Membership.Role.FINANCE)
    assert (
        capabilities_for_role(Membership.Role.COMMERCIAL).intersection(
            {
                Capability.SUPPLIER_READ,
                Capability.RESOURCE_READ,
                Capability.PURCHASE_READ,
            }
        )
        == set()
    )
    assert Capability.RESOURCE_READ_AVAILABILITY in capabilities_for_role(
        Membership.Role.COMMERCIAL
    )


@pytest.mark.django_db(transaction=True)
def test_resources_http_uses_explicit_commands_and_minimizes_commercial_overview() -> None:
    owner, organization_id, resource, _, _, _ = _physical_context("http")
    client, csrf = _authenticated_client(owner)
    base = f"/api/v1/organizations/{organization_id}/resources"
    created = client.post(
        f"{base}/units/create/",
        data={"code": "http-count", "name": "Conteo HTTP", "symbol": "hc", "dimension": "count"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert created.status_code == 201
    assert UUID(created.json()["id"])

    commercial = owner.__class__.objects.create_user(
        email=f"p12-commercial-{uuid4()}@example.test",
        password=P8_PASSWORD,
        status=owner.__class__.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    add_membership(
        organization_id=organization_id,
        user_id=commercial.pk,
        role=Membership.Role.COMMERCIAL,
    )
    client, csrf = _authenticated_client(commercial)
    overview = client.get(f"{base}/overview/")
    assert overview.status_code == 200
    assert overview.json()["resources"] == []
    assert overview.json()["suppliers"] == []
    assert overview.json()["purchases"] == []
    assert overview.json()["availability"][0]["resource_id"] == str(resource.pk)
    denied = client.post(
        f"{base}/suppliers/create/",
        data={"legal_name": "No autorizado", "internal_code": "DENIED"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert denied.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_direct_sql_cannot_confirm_incomplete_receipt_or_keep_terminal_capacity() -> None:
    owner, organization_id, resource, location, _, line = _physical_context("sql-guardian")
    receipt_line_id = uuid4()
    with (
        pytest.raises(IntegrityError),
        authorized_tenant_scope(owner, organization_id, Capability.PURCHASE_RECEIVE),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        receipt_id = uuid4()
        cursor.execute(
            "INSERT INTO resources_supplyreceipt "
            "(id, organization_id, purchase_id, reference, received_on, notes, "
            "recorded_by_membership_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, '', %s, now())",
            [
                receipt_id,
                organization_id,
                line.purchase_id,
                "SQL-INCOMPLETE",
                date.today(),
                line.purchase.created_by_membership_id,
            ],
        )
        cursor.execute(
            "INSERT INTO resources_supplyreceiptline "
            "(id, organization_id, receipt_id, purchase_line_id, resource_id, kind, "
            "quantity, destination_location_id, confirmed_at, "
            "recorded_by_membership_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, 'goods_received', 1, %s, now(), %s, now())",
            [
                receipt_line_id,
                organization_id,
                receipt_id,
                line.pk,
                resource.pk,
                location.pk,
                line.purchase.created_by_membership_id,
            ],
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        assert not SupplyReceiptLine.objects.filter(id=receipt_line_id).exists()
        assert not ResourceCapacityAllocation.objects.filter(
            organization_id=organization_id
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_orm_bulk_cannot_mutate_ledger_or_leave_assignment_without_projection() -> None:
    owner, organization_id, resource, location, _, line = _physical_context("bulk-ledger")
    movement = confirm_receipt_line(
        owner,
        organization_id,
        purchase_line_id=line.pk,
        receipt_reference="REC-BULK",
        received_on=date.today(),
        kind="goods_received",
        quantity="1",
        destination_location_id=location.pk,
        serial_numbers=[],
        notes="",
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        entry = StockMovement.objects.get(source_id=movement.pk)
    entry.reason = "Reescritura prohibida"
    with (
        pytest.raises(IntegrityError),
        authorized_tenant_scope(owner, organization_id, Capability.INVENTORY_RECORD_MOVEMENT),
    ):
        StockMovement.objects.bulk_update([entry], ["reason"])

    owner2, creation2, _, _, _, confirmed = _confirmed("p12-bulk-assignment")
    organization2 = creation2.organization.pk
    resource2, location2, _ = _resource_in_organization(
        owner2,
        organization2,
        "bulk-pool",
        Resource.Nature.REUSABLE_POOL,
        quantity="1",
    )
    requirement = create_requirement(
        owner2,
        organization2,
        reservation_id=confirmed["id"],
        resource_id=resource2.pk,
        quantity="1",
        reason="Bulk",
        idempotency_key=uuid4(),
    )
    with (
        pytest.raises(IntegrityError),
        authorized_tenant_scope(owner2, organization2, Capability.RESOURCE_RESERVE) as auth,
    ):
        ResourceAssignment.objects.bulk_create(
            [
                ResourceAssignment(
                    organization_id=organization2,
                    requirement=requirement,
                    root_reservation_id=requirement.root_reservation_id,
                    reservation_id=requirement.reservation_id,
                    resource=resource2,
                    source_location=location2,
                    quantity=requirement.quantity,
                    resource_interval=requirement.resource_interval,
                    recorded_by_membership_id=auth.membership_id,
                )
            ]
        )


@pytest.mark.django_db(transaction=True)
def test_scheduling_cancel_and_expiry_release_resource_capacity_transactionally() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("p12-cancel")
    organization_id = creation.organization.pk
    resource, location, _ = _resource_in_organization(
        owner,
        organization_id,
        "cancel-pool",
        Resource.Nature.REUSABLE_POOL,
        quantity="2",
    )
    requirement = create_requirement(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        resource_id=resource.pk,
        quantity="1",
        reason="Montaje base",
        idempotency_key=uuid4(),
    )
    assignment = reserve_resource(
        owner,
        organization_id,
        requirement_id=requirement.pk,
        source_location_id=location.pk,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )
    cancel_reservation(
        owner, organization_id, reservation_id=confirmed["id"], reason="Cancelación P12"
    )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        assignment.refresh_from_db()
        requirement.refresh_from_db()
        allocation = ResourceCapacityAllocation.objects.get(assignment=assignment)
        assert assignment.status == ResourceAssignment.Status.RELEASED
        assert requirement.status == ResourceRequirement.Status.CANCELLED
        assert not allocation.is_active

    owner2, creation2, _, _, provisional = _provisional("p12-expiry")
    organization2 = creation2.organization.pk
    resource2, location2, _ = _resource_in_organization(
        owner2,
        organization2,
        "expiry-pool",
        Resource.Nature.REUSABLE_POOL,
        quantity="1",
    )
    requirement2 = create_requirement(
        owner2,
        organization2,
        reservation_id=provisional["id"],
        resource_id=resource2.pk,
        quantity="1",
        reason="Hold",
        idempotency_key=uuid4(),
    )
    assignment2 = reserve_resource(
        owner2,
        organization2,
        requirement_id=requirement2.pk,
        source_location_id=location2.pk,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner2, organization2, Capability.RESERVATION_CANCEL) as auth:
        Reservation.objects.filter(pk=provisional["id"]).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1), revision=F("revision") + 1
        )
        assert expire_overdue_for_organization(auth) == 1
    with authorized_tenant_scope(owner2, organization2, Capability.RESOURCE_READ):
        assignment2.refresh_from_db()
        assert assignment2.status == ResourceAssignment.Status.RELEASED
        assert not ResourceCapacityAllocation.objects.get(assignment=assignment2).is_active


@pytest.mark.django_db(transaction=True)
def test_reschedule_moves_only_explicit_resources_and_replays_atomically() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("p12-reschedule")
    organization_id = creation.organization.pk
    resource, location, _ = _resource_in_organization(
        owner,
        organization_id,
        "reschedule-pool",
        Resource.Nature.REUSABLE_POOL,
        quantity="2",
    )
    assignments = []
    for position in range(2):
        requirement = create_requirement(
            owner,
            organization_id,
            reservation_id=confirmed["id"],
            resource_id=resource.pk,
            quantity="1",
            reason=f"Requerimiento {position}",
            idempotency_key=uuid4(),
        )
        assignments.append(
            reserve_resource(
                owner,
                organization_id,
                requirement_id=requirement.pk,
                source_location_id=location.pk,
                serialized_asset_id=None,
                idempotency_key=uuid4(),
            )
        )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        current = Reservation.objects.get(pk=confirmed["id"])
        original_interval = current.event_interval
        target_start = timezone.localtime(
            current.event_interval.lower + timedelta(days=1), ZoneInfo("America/Guayaquil")
        ).replace(tzinfo=None)
        target_end = timezone.localtime(
            current.event_interval.upper + timedelta(days=1), ZoneInfo("America/Guayaquil")
        ).replace(tzinfo=None)
        space_id = current.space_id
        revision = current.revision
    key = uuid4()
    result = reschedule_with_resources(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        revision=revision,
        idempotency_key=key,
        space_id=space_id,
        starts_at_local=target_start,
        ends_at_local=target_end,
        timezone_name="America/Guayaquil",
        reason="Cambio aprobado",
        commercial_terms_unchanged=True,
        carry_resource_assignment_ids=(assignments[0].pk,),
    )
    replay = reschedule_with_resources(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        revision=revision,
        idempotency_key=key,
        space_id=space_id,
        starts_at_local=target_start,
        ends_at_local=target_end,
        timezone_name="America/Guayaquil",
        reason="Cambio aprobado",
        commercial_terms_unchanged=True,
        carry_resource_assignment_ids=(assignments[0].pk,),
    )
    assert replay["reservation"]["id"] == result["reservation"]["id"]
    assert replay["carried_resource_assignment_ids"] == result["carried_resource_assignment_ids"]
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        old_rows = list(ResourceAssignment.objects.filter(pk__in=[row.pk for row in assignments]))
        successor = ResourceAssignment.objects.get(predecessor_assignment=assignments[0])
        assert all(row.status == ResourceAssignment.Status.RELEASED for row in old_rows)
        assert successor.status == ResourceAssignment.Status.RESERVED
        assert successor.requirement is not None
        assert successor.requirement.predecessor_requirement_id == assignments[0].requirement_id
        assert successor.resource_interval != original_interval
        assert not ResourceAssignment.objects.filter(predecessor_assignment=assignments[1]).exists()

        current = Reservation.objects.get(pk=result["reservation"]["id"])
        second_target_start = timezone.localtime(
            current.event_interval.lower + timedelta(days=1), ZoneInfo("America/Guayaquil")
        ).replace(tzinfo=None)
        second_target_end = timezone.localtime(
            current.event_interval.upper + timedelta(days=1), ZoneInfo("America/Guayaquil")
        ).replace(tzinfo=None)
        second_revision = current.revision
    full = reschedule_with_resources(
        owner,
        organization_id,
        reservation_id=result["reservation"]["id"],
        revision=second_revision,
        idempotency_key=uuid4(),
        space_id=space_id,
        starts_at_local=second_target_start,
        ends_at_local=second_target_end,
        timezone_name="America/Guayaquil",
        reason="Segundo cambio aprobado",
        commercial_terms_unchanged=True,
        carry_resource_assignment_ids=(successor.pk,),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        successor.refresh_from_db()
        newest = ResourceAssignment.objects.get(predecessor_assignment=successor)
        assert successor.status == ResourceAssignment.Status.RELEASED
        assert newest.status == ResourceAssignment.Status.RESERVED
        assert newest.reservation_id == UUID(str(full["reservation"]["id"]))

        current = Reservation.objects.get(pk=full["reservation"]["id"])
        conflict_target_start = timezone.localtime(
            current.event_interval.lower + timedelta(days=1), ZoneInfo("America/Guayaquil")
        ).replace(tzinfo=None)
        conflict_target_end = timezone.localtime(
            current.event_interval.upper + timedelta(days=1), ZoneInfo("America/Guayaquil")
        ).replace(tzinfo=None)
        conflict_revision = current.revision
        reservation_count = Reservation.objects.count()
    with pytest.raises(ResourcesError):
        reschedule_with_resources(
            owner,
            organization_id,
            reservation_id=full["reservation"]["id"],
            revision=conflict_revision,
            idempotency_key=uuid4(),
            space_id=space_id,
            starts_at_local=conflict_target_start,
            ends_at_local=conflict_target_end,
            timezone_name="America/Guayaquil",
            reason="Cambio inválido",
            commercial_terms_unchanged=True,
            carry_resource_assignment_ids=(uuid4(),),
        )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        current.refresh_from_db()
        newest.refresh_from_db()
        assert current.status == Reservation.Status.CONFIRMED
        assert current.revision == conflict_revision
        assert newest.status == ResourceAssignment.Status.RESERVED
        assert Reservation.objects.count() == reservation_count


@pytest.mark.django_db(transaction=True)
def test_direct_sql_terminal_transition_releases_resources_or_rolls_back_together() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("p12-sql-schedule-release")
    organization_id = creation.organization.pk
    resource, location, _ = _resource_in_organization(
        owner,
        organization_id,
        "sql-schedule-pool",
        Resource.Nature.REUSABLE_POOL,
        quantity="1",
    )
    requirement = create_requirement(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        resource_id=resource.pk,
        quantity="1",
        reason="Protección SQL",
        idempotency_key=uuid4(),
    )
    assignment = reserve_resource(
        owner,
        organization_id,
        requirement_id=requirement.pk,
        source_location_id=location.pk,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )
    membership = Membership.objects.get(organization_id=organization_id, user=owner)

    with (
        pytest.raises(IntegrityError),
        authorized_tenant_scope(owner, organization_id, Capability.RESERVATION_CANCEL),
        transaction.atomic(),
    ):
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.commercial_reservation
                SET status = 'cancelled', revision = revision + 1,
                    cancelled_at = %s, cancelled_by_membership_id = %s,
                    cancellation_reason = %s, updated_at = %s
                WHERE organization_id = %s AND id = %s
                """,
                [
                    now,
                    membership.pk,
                    "Ruta SQL sin consecuencias Operations",
                    now,
                    organization_id,
                    confirmed["id"],
                ],
            )
        assignment.refresh_from_db()
        assert assignment.status == ResourceAssignment.Status.RELEASED
        assert not ResourceCapacityAllocation.objects.get(assignment=assignment).is_active
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        assignment.refresh_from_db()
        reservation = Reservation.objects.get(pk=confirmed["id"])
        assert reservation.status == Reservation.Status.CONFIRMED
        assert assignment.status == ResourceAssignment.Status.RESERVED
        assert ResourceCapacityAllocation.objects.get(assignment=assignment).is_active


@pytest.mark.django_db(transaction=True)
def test_resources_receipt_materializes_exactly_one_finance_fact_and_never_cash() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("p12-finance")
    organization_id = creation.organization.pk
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    _, _, receipt = _resource_in_organization(
        owner,
        organization_id,
        "finance-service",
        Resource.Nature.SUPPLIED_SERVICE,
        quantity="2",
        declared_capacity="3",
        root_reservation_id=UUID(str(confirmed["root_id"])),
        venue_id=venue_id,
    )
    today = date.today()
    starts_on = today.replace(day=1)
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
        label="P12",
        idempotency_key=uuid4(),
    )
    category = create_category(
        owner,
        organization_id,
        kind=FinanceCategory.Kind.DIRECT_COST,
        name="Suministro P12",
        idempotency_key=uuid4(),
    )
    key = uuid4()
    command: _MaterializeCommand = {
        "receipt_line_id": receipt.pk,
        "target_kind": "actual_direct_cost",
        "category_id": category.pk,
        "amount": Decimal("125.50"),
        "currency": "USD",
        "economic_date": today,
        "description": "Servicio recibido",
        "evidence_reference": "REC-P12",
        "root_reservation_id": UUID(str(confirmed["root_id"])),
        "venue_id": venue_id,
        "expense_type": None,
        "allocations": (),
        "idempotency_key": key,
    }
    result = materialize_resources_receipt(owner, organization_id, **command)
    replay = materialize_resources_receipt(owner, organization_id, **command)
    assert replay == result
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        actual = ActualDirectCost.objects.get(pk=UUID(str(result["target_id"])))
        reference = FinancialSourceReference.objects.get(source_id=receipt.pk)
        assert actual.provenance == ActualDirectCost.Provenance.RESOURCES_RECEIPT
        assert reference.actual_direct_cost_id == actual.pk
        assert reference.expense_occurrence_id is None
        assert not OperatingCashMovement.objects.filter(organization_id=organization_id).exists()
    conflicting = command.copy()
    conflicting["idempotency_key"] = uuid4()
    with pytest.raises(ResourcesError) as raised:
        materialize_resources_receipt(owner, organization_id, **conflicting)
    assert raised.value.code == "resources_receipt_already_materialized"

    _, _, expense_receipt = _resource_in_organization(
        owner,
        organization_id,
        "finance-expense",
        Resource.Nature.SUPPLIED_SERVICE,
        quantity="1",
        declared_capacity="1",
    )
    expense_category = create_category(
        owner,
        organization_id,
        kind=FinanceCategory.Kind.VARIABLE_EXPENSE,
        name="Gasto P12",
        idempotency_key=uuid4(),
    )
    expense_result = materialize_resources_receipt(
        owner,
        organization_id,
        receipt_line_id=expense_receipt.pk,
        target_kind="expense_occurrence",
        category_id=expense_category.pk,
        amount=Decimal("40.00"),
        currency="USD",
        economic_date=today,
        description="Gasto recibido",
        evidence_reference="REC-EXP-P12",
        root_reservation_id=None,
        venue_id=None,
        expense_type="variable",
        allocations=(
            {
                "scope": "business",
                "root_reservation_id": None,
                "venue_id": None,
                "amount": Decimal("40.00"),
            },
        ),
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        expense = ExpenseOccurrence.objects.get(pk=UUID(str(expense_result["target_id"])))
        assert expense.provenance == ExpenseOccurrence.Provenance.RESOURCES_RECEIPT
        assert expense.recurring_rule_id is None


@pytest.mark.django_db(transaction=True)
def test_maintenance_blocks_pool_then_custody_and_return_preserve_physical_history() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("p12-maintenance")
    organization_id = creation.organization.pk
    resource, location, _ = _resource_in_organization(
        owner,
        organization_id,
        "maintenance-pool",
        Resource.Nature.REUSABLE_POOL,
        quantity="1",
    )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        schedule = Reservation.objects.get(pk=confirmed["id"]).event_interval
    unavailable = record_unavailability(
        owner,
        organization_id,
        resource_id=resource.pk,
        serialized_asset_id=None,
        location_id=location.pk,
        quantity="1",
        starts_at=schedule.lower,
        ends_at=schedule.upper,
        reason="Mantenimiento preventivo",
        maintenance_description="Inspección programada",
        corrects_id=None,
        idempotency_key=uuid4(),
    )
    requirement = create_requirement(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        resource_id=resource.pk,
        quantity="1",
        reason="Equipo operativo",
        idempotency_key=uuid4(),
    )
    assert requirement.status == ResourceRequirement.Status.SHORTAGE
    with pytest.raises(ResourcesError) as shortage:
        reserve_resource(
            owner,
            organization_id,
            requirement_id=requirement.pk,
            source_location_id=location.pk,
            serialized_asset_id=None,
            idempotency_key=uuid4(),
        )
    assert shortage.value.code == "resource_shortage"
    close_unavailability(
        owner,
        organization_id,
        unavailability_id=unavailable.pk,
        idempotency_key=uuid4(),
    )
    assignment = reserve_resource(
        owner,
        organization_id,
        requirement_id=requirement.pk,
        source_location_id=location.pk,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )
    issued = execute_assignment(
        owner,
        organization_id,
        assignment_id=assignment.pk,
        action="issue",
        notes="Entrega al responsable",
        idempotency_key=uuid4(),
    )
    assert issued.status == ResourceAssignment.Status.CUSTODY
    cancel_reservation(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        reason="Cancelación con equipo entregado",
    )
    returned = execute_assignment(
        owner,
        organization_id,
        assignment_id=assignment.pk,
        action="return",
        notes="Equipo devuelto",
        idempotency_key=uuid4(),
    )
    assert returned.status == ResourceAssignment.Status.RETURNED
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        allocation = ResourceCapacityAllocation.objects.get(assignment=assignment)
        maintenance = MaintenanceRecord.objects.get(unavailability=unavailable)
        balance = StockBalance.objects.get(resource=resource, location=location)
        movement_kinds = list(
            StockMovement.objects.filter(resource=resource).values_list("kind", flat=True)
        )
        assert not allocation.is_active
        assert maintenance.status == MaintenanceRecord.Status.COMPLETED
        assert balance.quantity == Decimal("1.000000")
        assert StockMovement.Kind.EXIT in movement_kinds
        assert StockMovement.Kind.RETURN in movement_kinds
