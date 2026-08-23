# ruff: noqa: DJ001, DJ008

from __future__ import annotations

import uuid

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import Q


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Supplier(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        INACTIVE = "inactive", "Inactivo"

    legal_name = models.CharField(max_length=180)
    normalized_legal_name = models.CharField(max_length=180)
    tax_identifier = models.CharField(max_length=32, null=True, blank=True)
    internal_code = models.CharField(max_length=48, null=True, blank=True)
    identity_key = models.CharField(max_length=220)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    inactive_reason = models.CharField(max_length=500, null=True, blank=True)
    inactive_at = models.DateTimeField(null=True, blank=True)
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resource_suppliers"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_supplier_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "identity_key"], name="resources_supplier_identity_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "tax_identifier"],
                condition=Q(tax_identifier__isnull=False),
                name="resources_supplier_tax_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "internal_code"],
                condition=Q(internal_code__isnull=False),
                name="resources_supplier_internal_code_uq",
            ),
            models.CheckConstraint(
                condition=Q(tax_identifier__isnull=False) | Q(internal_code__isnull=False),
                name="resources_supplier_identity_source_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="active", inactive_at__isnull=True, inactive_reason__isnull=True)
                    | Q(status="inactive", inactive_at__isnull=False, inactive_reason__isnull=False)
                ),
                name="resources_supplier_status_ck",
            ),
        ]
        ordering = ["legal_name", "id"]


class SupplierContact(TenantModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="contacts")
    person_id = models.UUIDField()
    responsibility = models.CharField(max_length=120)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    linked_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="supplier_contacts"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_contact_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "supplier", "person_id"],
                condition=Q(is_active=True),
                name="resources_contact_person_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "supplier"],
                condition=Q(is_primary=True, is_active=True),
                name="resources_contact_primary_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, valid_until__isnull=True)
                    | Q(is_active=False, valid_until__isnull=False)
                ),
                name="resources_contact_validity_ck",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="resources_contact_dates_ck",
            ),
        ]


class UnitDefinition(TenantModel):
    class Dimension(models.TextChoices):
        COUNT = "count", "Conteo"
        MASS = "mass", "Masa"
        VOLUME = "volume", "Volumen"
        LENGTH = "length", "Longitud"
        DURATION = "duration", "Duración"

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=80)
    symbol = models.CharField(max_length=16)
    dimension = models.CharField(max_length=12, choices=Dimension.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="resources_unit_org_id_uq"),
            models.UniqueConstraint(fields=["organization", "code"], name="resources_unit_code_uq"),
        ]
        ordering = ["dimension", "code"]


class UnitConversion(TenantModel):
    from_unit = models.ForeignKey(
        UnitDefinition, on_delete=models.PROTECT, related_name="conversions_from"
    )
    to_unit = models.ForeignKey(
        UnitDefinition, on_delete=models.PROTECT, related_name="conversions_to"
    )
    multiplier = models.DecimalField(max_digits=24, decimal_places=12)
    revision = models.PositiveIntegerField()
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_conversion_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "from_unit", "to_unit", "revision"],
                name="resources_conversion_revision_uq",
            ),
            models.CheckConstraint(
                condition=Q(multiplier__gt=0), name="resources_conversion_positive_ck"
            ),
            models.CheckConstraint(
                condition=~Q(from_unit=models.F("to_unit")), name="resources_conversion_distinct_ck"
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="resources_conversion_dates_ck",
            ),
        ]


class Resource(TenantModel):
    class Nature(models.TextChoices):
        SUPPLIED_SERVICE = "supplied_service", "Servicio suministrado"
        CONSUMABLE = "consumable", "Consumible"
        REUSABLE_POOL = "reusable_pool", "Pool reutilizable"
        SERIALIZED_ASSET = "serialized_asset", "Activo serializado"

    name = models.CharField(max_length=160)
    normalized_name = models.CharField(max_length=160)
    nature = models.CharField(max_length=20, choices=Nature.choices)
    base_unit = models.ForeignKey(UnitDefinition, on_delete=models.PROTECT)
    declared_capacity = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    inactive_reason = models.CharField(max_length=500, null=True, blank=True)
    inactive_at = models.DateTimeField(null=True, blank=True)
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resources_created"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_resource_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "normalized_name", "nature"],
                name="resources_resource_name_uq",
            ),
            models.CheckConstraint(
                condition=Q(declared_capacity__isnull=True) | Q(declared_capacity__gt=0),
                name="resources_capacity_positive_ck",
            ),
            models.CheckConstraint(
                condition=Q(nature="supplied_service") | Q(declared_capacity__isnull=True),
                name="resources_capacity_service_only_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, inactive_at__isnull=True, inactive_reason__isnull=True)
                    | Q(is_active=False, inactive_at__isnull=False, inactive_reason__isnull=False)
                ),
                name="resources_resource_active_ck",
            ),
        ]
        ordering = ["name", "id"]


class SupplierTermRevision(TenantModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="term_revisions")
    revision = models.PositiveIntegerField()
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=300)
    lead_time_days = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=500, blank=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="supplier_terms"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="resources_term_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "supplier", "revision"], name="resources_term_revision_uq"
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="resources_term_validity_ck",
            ),
        ]
        ordering = ["supplier", "revision"]


class SupplierOffering(TenantModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="offerings")
    resource = models.ForeignKey(
        Resource, on_delete=models.PROTECT, related_name="supplier_offerings"
    )
    supplier_reference = models.CharField(max_length=80, blank=True)
    minimum_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="supplier_offerings"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_offering_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "supplier", "resource", "valid_from"],
                name="resources_offering_validity_uq",
            ),
            models.CheckConstraint(
                condition=Q(minimum_quantity__gt=0), name="resources_offering_quantity_ck"
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="resources_offering_dates_ck",
            ),
        ]


class InventoryLocation(TenantModel):
    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.PROTECT, related_name="inventory_locations"
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_location_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "venue", "code"], name="resources_location_code_uq"
            ),
        ]
        ordering = ["venue", "code"]


class Purchase(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        ORDERED = "ordered", "Ordenada"
        CLOSED = "closed", "Cerrada"
        CANCELLED = "cancelled", "Cancelada"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    reference = models.CharField(max_length=100)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    ordered_on = models.DateField(null=True, blank=True)
    root_reservation_id = models.UUIDField(null=True, blank=True)
    venue_id = models.UUIDField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resource_purchases"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_purchase_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "reference"], name="resources_purchase_reference_uq"
            ),
            models.CheckConstraint(
                condition=(
                    Q(root_reservation_id__isnull=True, venue_id__isnull=True)
                    | Q(root_reservation_id__isnull=False, venue_id__isnull=False)
                ),
                name="resources_purchase_event_scope_ck",
            ),
        ]


class PurchaseLine(TenantModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="lines")
    position = models.PositiveIntegerField()
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="purchase_lines")
    ordered_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    procurement_unit_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    procurement_currency = models.CharField(max_length=3, null=True, blank=True)
    description = models.CharField(max_length=300)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_purchaseline_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "purchase", "position"],
                name="resources_purchaseline_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(ordered_quantity__gt=0), name="resources_purchaseline_quantity_ck"
            ),
            models.CheckConstraint(
                condition=(
                    Q(procurement_unit_amount__isnull=True, procurement_currency__isnull=True)
                    | Q(procurement_unit_amount__gt=0, procurement_currency__isnull=False)
                ),
                name="resources_purchaseline_procurement_ck",
            ),
        ]
        ordering = ["position", "id"]


class SupplyReceipt(TenantModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="receipts")
    reference = models.CharField(max_length=100)
    received_on = models.DateField()
    notes = models.CharField(max_length=500, blank=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="supply_receipts"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_receipt_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "reference"], name="resources_receipt_reference_uq"
            ),
        ]


class SupplyReceiptLine(TenantModel):
    class Kind(models.TextChoices):
        GOODS_RECEIVED = "goods_received", "Bien recibido"
        SERVICE_FULFILLED = "service_fulfilled", "Servicio cumplido"

    receipt = models.ForeignKey(SupplyReceipt, on_delete=models.PROTECT, related_name="lines")
    purchase_line = models.ForeignKey(
        PurchaseLine, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="receipt_lines")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    destination_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.PROTECT,
        related_name="receipt_lines",
        null=True,
        blank=True,
    )
    confirmed_at = models.DateTimeField()
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="supply_receipt_lines"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_receiptline_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="resources_receiptline_quantity_ck"
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="goods_received", destination_location__isnull=False)
                    | Q(kind="service_fulfilled", destination_location__isnull=True)
                ),
                name="resources_receiptline_location_ck",
            ),
        ]


class SerializedAsset(TenantModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        RESERVED = "reserved", "Reservado"
        CUSTODY = "custody", "En custodia"
        MAINTENANCE = "maintenance", "Mantenimiento"
        RETIRED = "retired", "Retirado"

    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="assets")
    receipt_line = models.ForeignKey(
        SupplyReceiptLine,
        on_delete=models.PROTECT,
        related_name="serialized_assets",
        null=True,
        blank=True,
    )
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="assets")
    serial_number = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_asset_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "resource", "serial_number"],
                name="resources_asset_serial_uq",
            ),
        ]


class StockBalance(TenantModel):
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="stock_balances")
    location = models.ForeignKey(
        InventoryLocation, on_delete=models.PROTECT, related_name="stock_balances"
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_balance_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "resource", "location"], name="resources_balance_scope_uq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0), name="resources_balance_nonnegative_ck"
            ),
        ]


class StockMovement(TenantModel):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada"
        EXIT = "exit", "Salida"
        ADJUSTMENT = "adjustment", "Ajuste"
        TRANSFER_OUT = "transfer_out", "Traslado salida"
        TRANSFER_IN = "transfer_in", "Traslado entrada"
        RETURN = "return", "Devolución"
        CORRECTION = "correction", "Corrección"

    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta"
        DECREASE = "decrease", "Disminuye"

    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="movements")
    location = models.ForeignKey(
        InventoryLocation, on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    direction = models.CharField(max_length=12, choices=Direction.choices)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    effect = models.DecimalField(max_digits=20, decimal_places=6)
    reason = models.CharField(max_length=500)
    transfer_group = models.UUIDField(null=True, blank=True)
    other_location_id = models.UUIDField(null=True, blank=True)
    source_kind = models.CharField(max_length=40, null=True, blank=True)
    source_id = models.UUIDField(null=True, blank=True)
    corrects = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="corrections", null=True, blank=True
    )
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="stock_movements"
    )
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_movement_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "source_kind", "source_id"],
                condition=Q(source_kind="resources_receipt_line"),
                name="resources_movement_receipt_source_uq",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="resources_movement_quantity_ck"
            ),
            models.CheckConstraint(condition=~Q(effect=0), name="resources_movement_effect_ck"),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind__in=[
                            "entry",
                            "return",
                            "transfer_in",
                            "adjustment",
                            "correction",
                        ],
                        direction="increase",
                        effect=models.F("quantity"),
                    )
                    | Q(
                        kind__in=["exit", "transfer_out", "adjustment", "correction"],
                        direction="decrease",
                        effect=-models.F("quantity"),
                    )
                ),
                name="resources_movement_direction_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind__in=["transfer_in", "transfer_out"],
                        transfer_group__isnull=False,
                        other_location_id__isnull=False,
                    )
                    | ~Q(kind__in=["transfer_in", "transfer_out"])
                ),
                name="resources_movement_transfer_ck",
            ),
            models.CheckConstraint(
                condition=Q(kind="correction", corrects__isnull=False) | ~Q(kind="correction"),
                name="resources_movement_correction_ck",
            ),
        ]


class ResourceRequirement(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", "Abierto"
        SHORTAGE = "shortage", "Faltante"
        SATISFIED = "satisfied", "Satisfecho"
        CANCELLED = "cancelled", "Cancelado"

    root_reservation_id = models.UUIDField()
    reservation_id = models.UUIDField()
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="requirements")
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    resource_interval = DateTimeRangeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    reason = models.CharField(max_length=500, blank=True)
    predecessor_requirement = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="successor_requirements",
        null=True,
        blank=True,
    )
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resource_requirements"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_requirement_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="resources_requirement_quantity_ck"
            ),
        ]


class ResourceAssignment(TenantModel):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reservado"
        ISSUED = "issued", "Consumido/entregado"
        CUSTODY = "custody", "En custodia"
        FULFILLED = "fulfilled", "Cumplido"
        RETURNED = "returned", "Devuelto"
        RELEASED = "released", "Liberado"
        CANCELLED = "cancelled", "Cancelado"

    requirement = models.ForeignKey(
        ResourceRequirement,
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )
    root_reservation_id = models.UUIDField()
    reservation_id = models.UUIDField()
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="assignments")
    serialized_asset = models.ForeignKey(
        SerializedAsset, on_delete=models.PROTECT, related_name="assignments", null=True, blank=True
    )
    source_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    resource_interval = DateTimeRangeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RESERVED)
    predecessor_assignment = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="successor_assignments",
        null=True,
        blank=True,
    )
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resource_assignments"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_assignment_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="resources_assignment_quantity_ck"
            ),
            models.CheckConstraint(
                condition=Q(serialized_asset__isnull=True) | Q(quantity=1),
                name="resources_assignment_asset_quantity_ck",
            ),
        ]


class ResourceCapacityAllocation(TenantModel):
    class Basis(models.TextChoices):
        SCHEDULING = "scheduling", "Reserva scheduling"
        CUSTODY = "custody", "Custodia física"

    assignment = models.OneToOneField(
        ResourceAssignment, on_delete=models.PROTECT, related_name="capacity_allocation"
    )
    reservation_id = models.UUIDField()
    resource = models.ForeignKey(
        Resource, on_delete=models.PROTECT, related_name="capacity_allocations"
    )
    serialized_asset = models.ForeignKey(
        SerializedAsset,
        on_delete=models.PROTECT,
        related_name="capacity_allocations",
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    resource_interval = DateTimeRangeField()
    basis = models.CharField(max_length=12, choices=Basis.choices, default=Basis.SCHEDULING)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_allocation_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="resources_allocation_quantity_ck"
            ),
            models.CheckConstraint(
                condition=Q(basis__in=["scheduling", "custody"]),
                name="resources_allocation_basis_ck",
            ),
            ExclusionConstraint(
                name="resources_asset_allocation_excl",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("serialized_asset", RangeOperators.EQUAL),
                    ("resource_interval", RangeOperators.OVERLAPS),
                ],
                condition=Q(is_active=True, serialized_asset__isnull=False),
            ),
        ]


class CustodyEvent(TenantModel):
    class Kind(models.TextChoices):
        DELIVERY = "delivery", "Entrega"
        CUSTODY = "custody", "Custodia"
        RETURN = "return", "Devolución"

    assignment = models.ForeignKey(
        ResourceAssignment, on_delete=models.PROTECT, related_name="custody_events"
    )
    serialized_asset = models.ForeignKey(
        SerializedAsset,
        on_delete=models.PROTECT,
        related_name="custody_events",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    occurred_at = models.DateTimeField()
    notes = models.CharField(max_length=500, blank=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="custody_events"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_custody_org_id_uq"
            )
        ]


class ResourceUnavailability(TenantModel):
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="unavailability")
    serialized_asset = models.ForeignKey(
        SerializedAsset,
        on_delete=models.PROTECT,
        related_name="unavailability",
        null=True,
        blank=True,
    )
    location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.PROTECT,
        related_name="unavailability",
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    unavailable_interval = DateTimeRangeField()
    reason = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    corrects = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="corrections", null=True, blank=True
    )
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resource_unavailability"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_unavailability_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="resources_unavailability_quantity_ck"
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, closed_at__isnull=True)
                    | Q(is_active=False, closed_at__isnull=False)
                ),
                name="resources_unavailability_state_ck",
            ),
            ExclusionConstraint(
                name="resources_asset_unavailable_excl",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("serialized_asset", RangeOperators.EQUAL),
                    ("unavailable_interval", RangeOperators.OVERLAPS),
                ],
                condition=Q(is_active=True, serialized_asset__isnull=False),
            ),
        ]


class MaintenanceRecord(TenantModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programado"
        IN_PROGRESS = "in_progress", "En curso"
        COMPLETED = "completed", "Completado"
        CANCELLED = "cancelled", "Cancelado"

    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="maintenance")
    serialized_asset = models.ForeignKey(
        SerializedAsset, on_delete=models.PROTECT, related_name="maintenance", null=True, blank=True
    )
    unavailability = models.OneToOneField(
        ResourceUnavailability, on_delete=models.PROTECT, related_name="maintenance"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)
    description = models.CharField(max_length=500)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="resource_maintenance"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_maintenance_org_id_uq"
            )
        ]


class ResourceEvent(TenantModel):
    aggregate_kind = models.CharField(max_length=40)
    aggregate_id = models.UUIDField()
    kind = models.CharField(max_length=48)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()
    recorded_by_membership_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="resources_event_org_id_uq")
        ]
        ordering = ["occurred_at", "id"]


class ResourceCommand(TenantModel):
    command_type = models.CharField(max_length=48)
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)
    result_type = models.CharField(max_length=48)
    result_reference = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="resources_command_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "command_type", "idempotency_key"],
                name="resources_command_idempotency_uq",
            ),
        ]
