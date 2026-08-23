from datetime import date

from rest_framework import serializers

from .models import Resource, StockMovement, SupplyReceiptLine, UnitDefinition


class ErrorSerializer(serializers.Serializer[dict[str, object]]):
    error = serializers.JSONField()


class EntitySerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()


class CapabilitiesSerializer(serializers.Serializer[dict[str, object]]):
    capabilities = serializers.ListField(child=serializers.CharField())


class OverviewSerializer(serializers.Serializer[dict[str, object]]):
    organization_id = serializers.UUIDField()
    capabilities = serializers.ListField(child=serializers.CharField())
    availability = serializers.ListField(child=serializers.JSONField())
    resources = serializers.ListField(child=serializers.JSONField())
    units = serializers.ListField(child=serializers.JSONField())
    conversions = serializers.ListField(child=serializers.JSONField())
    locations = serializers.ListField(child=serializers.JSONField())
    balances = serializers.ListField(child=serializers.JSONField())
    assets = serializers.ListField(child=serializers.JSONField())
    movements = serializers.ListField(child=serializers.JSONField())
    requirements = serializers.ListField(child=serializers.JSONField())
    assignments = serializers.ListField(child=serializers.JSONField())
    unavailability = serializers.ListField(child=serializers.JSONField())
    maintenance = serializers.ListField(child=serializers.JSONField())
    suppliers = serializers.ListField(child=serializers.JSONField())
    purchases = serializers.ListField(child=serializers.JSONField())
    receipts = serializers.ListField(child=serializers.JSONField())


class UnitCreateSerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=80)
    symbol = serializers.CharField(max_length=16)
    dimension = serializers.ChoiceField(choices=UnitDefinition.Dimension.choices)


class ConversionCreateSerializer(serializers.Serializer[dict[str, object]]):
    from_unit_id = serializers.UUIDField()
    to_unit_id = serializers.UUIDField()
    multiplier = serializers.DecimalField(max_digits=24, decimal_places=12)
    valid_from = serializers.DateField(required=False, default=date.today)
    valid_until = serializers.DateField(allow_null=True, required=False, default=None)


class SupplierCreateSerializer(serializers.Serializer[dict[str, object]]):
    legal_name = serializers.CharField(max_length=180)
    tax_identifier = serializers.CharField(
        max_length=32, allow_blank=True, allow_null=True, required=False, default=None
    )
    internal_code = serializers.CharField(
        max_length=48, allow_blank=True, allow_null=True, required=False, default=None
    )


class ActiveSerializer(serializers.Serializer[dict[str, object]]):
    active = serializers.BooleanField()
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class SupplierContactCreateSerializer(serializers.Serializer[dict[str, object]]):
    person_id = serializers.UUIDField()
    responsibility = serializers.CharField(max_length=120)
    is_primary = serializers.BooleanField(default=False)
    valid_from = serializers.DateField(required=False, default=date.today)


class ContactInactivateSerializer(serializers.Serializer[dict[str, object]]):
    valid_until = serializers.DateField(required=False, default=date.today)


class SupplierTermCreateSerializer(serializers.Serializer[dict[str, object]]):
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True, required=False, default=None)
    payment_terms = serializers.CharField(max_length=300)
    lead_time_days = serializers.IntegerField(min_value=0)
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class SupplierOfferingCreateSerializer(serializers.Serializer[dict[str, object]]):
    resource_id = serializers.UUIDField()
    supplier_reference = serializers.CharField(
        max_length=80, allow_blank=True, required=False, default=""
    )
    minimum_quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True, required=False, default=None)


class ResourceCreateSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=160)
    nature = serializers.ChoiceField(choices=Resource.Nature.choices)
    base_unit_id = serializers.UUIDField()
    declared_capacity = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, required=False, default=None
    )


class LocationCreateSerializer(serializers.Serializer[dict[str, object]]):
    venue_id = serializers.UUIDField()
    code = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=120)


class PurchaseLineCreateSerializer(serializers.Serializer[dict[str, object]]):
    resource_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    procurement_unit_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True, required=False, default=None
    )
    procurement_currency = serializers.CharField(
        min_length=3, max_length=3, allow_null=True, required=False, default=None
    )
    description = serializers.CharField(max_length=300)


class PurchaseCreateSerializer(serializers.Serializer[dict[str, object]]):
    supplier_id = serializers.UUIDField()
    reference = serializers.CharField(max_length=100)
    ordered_on = serializers.DateField(allow_null=True, required=False, default=None)
    root_reservation_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    venue_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")
    lines = PurchaseLineCreateSerializer(many=True, allow_empty=False)


class ReceiptLineCreateSerializer(serializers.Serializer[dict[str, object]]):
    purchase_line_id = serializers.UUIDField()
    receipt_reference = serializers.CharField(max_length=100)
    received_on = serializers.DateField()
    kind = serializers.ChoiceField(choices=SupplyReceiptLine.Kind.choices)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    destination_location_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    serial_numbers = serializers.ListField(
        child=serializers.CharField(max_length=120), required=False, default=list
    )
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class MovementCreateSerializer(serializers.Serializer[dict[str, object]]):
    resource_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=[*StockMovement.Kind.choices, ("transfer", "Traslado")])
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    direction = serializers.ChoiceField(
        choices=StockMovement.Direction.choices, allow_null=True, required=False, default=None
    )
    reason = serializers.CharField(max_length=500)
    other_location_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    corrects_id = serializers.UUIDField(allow_null=True, required=False, default=None)


class RequirementCreateSerializer(serializers.Serializer[dict[str, object]]):
    reservation_id = serializers.UUIDField()
    resource_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class AssignmentCreateSerializer(serializers.Serializer[dict[str, object]]):
    requirement_id = serializers.UUIDField()
    source_location_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    serialized_asset_id = serializers.UUIDField(allow_null=True, required=False, default=None)


class AssignmentActionSerializer(serializers.Serializer[dict[str, object]]):
    action = serializers.ChoiceField(choices=("issue", "fulfill", "return"))
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class UnavailabilityCreateSerializer(serializers.Serializer[dict[str, object]]):
    resource_id = serializers.UUIDField()
    serialized_asset_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    location_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=500)
    maintenance_description = serializers.CharField(
        max_length=500, allow_blank=True, allow_null=True, required=False, default=None
    )
    corrects_id = serializers.UUIDField(allow_null=True, required=False, default=None)


class FinanceAllocationSerializer(serializers.Serializer[dict[str, object]]):
    scope = serializers.ChoiceField(choices=("business", "venue", "event"))
    root_reservation_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    venue_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class FinancialMaterializationSerializer(serializers.Serializer[dict[str, object]]):
    target_kind = serializers.ChoiceField(choices=("actual_direct_cost", "expense_occurrence"))
    category_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    economic_date = serializers.DateField()
    description = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300)
    root_reservation_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    venue_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    expense_type = serializers.ChoiceField(
        choices=("variable", "recurring"), allow_null=True, required=False, default=None
    )
    allocations = FinanceAllocationSerializer(many=True, required=False, default=list)
