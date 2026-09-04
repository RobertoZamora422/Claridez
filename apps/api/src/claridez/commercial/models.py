from __future__ import annotations

import uuid

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round

from claridez.catalog.models import CatalogItemRevision, CatalogPrice, EventType
from claridez.organizations.models import Membership, Organization, Space, Venue
from claridez.people.models import ContactOrigin as ContactOrigin
from claridez.people.models import Person as Person
from claridez.people.models import PersonRevision as PersonRevision


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class EventRequest(TenantModel):
    class Status(models.TextChoices):
        NEW = "new", "Nueva"
        QUOTED = "quoted", "Cotizada"
        ACCEPTED = "accepted", "Aceptada"
        CONFIRMED = "confirmed", "Confirmada"
        CLOSED_LOST = "closed_lost", "Perdida"
        CANCELLED = "cancelled", "Cancelada"

    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="event_requests", db_index=False
    )
    event_type_definition = models.ForeignKey(
        EventType, on_delete=models.PROTECT, related_name="event_requests", db_index=False
    )
    space = models.ForeignKey(
        Space, on_delete=models.PROTECT, related_name="event_requests", db_index=False
    )
    event_type = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    event_timezone = models.CharField(max_length=64)
    estimated_guests = models.PositiveIntegerField()
    general_need = models.CharField(max_length=500)
    notes = models.TextField(blank=True)
    origin = models.CharField(max_length=24, choices=ContactOrigin.choices)
    origin_detail = models.CharField(max_length=160, blank=True)
    responsible_membership = models.ForeignKey(Membership, on_delete=models.PROTECT, db_index=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    revision = models.PositiveIntegerField(default=1)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_eventrequest_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(starts_at__lt=F("ends_at")),
                name="commercial_eventrequest_interval_valid",
            ),
            models.CheckConstraint(
                condition=Q(estimated_guests__gte=1), name="commercial_eventrequest_guests_positive"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="commercial_eventrequest_revision_positive"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "new",
                        "quoted",
                        "accepted",
                        "confirmed",
                        "closed_lost",
                        "cancelled",
                    ]
                ),
                name="commercial_eventrequest_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}@{self.starts_at.isoformat()}"


class EventRequestHistory(models.Model):
    class Kind(models.TextChoices):
        CUTOVER_STATE = "cutover_state", "Estado existente al corte"
        CREATED = "created", "Creación"
        UPDATED = "updated", "Actualización"
        STATUS_CHANGED = "status_changed", "Cambio de estado"

    class Provenance(models.TextChoices):
        CUTOVER_SNAPSHOT = "cutover_snapshot", "Snapshot de corte"
        DATABASE = "database", "Registro de base de datos"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    event_request = models.ForeignKey(
        EventRequest, on_delete=models.PROTECT, related_name="history", db_index=False
    )
    analytics_person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        null=True,
        editable=False,
        related_name="request_identity_evidence",
        db_index=False,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=EventRequest.Status.choices)
    request_revision = models.PositiveIntegerField()
    origin = models.CharField(max_length=24, choices=ContactOrigin.choices)
    origin_detail = models.CharField(max_length=160, blank=True)
    responsible_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="request_history_responsibilities",
        db_index=False,
    )
    actor_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="event_request_history_actions",
        null=True,
        blank=True,
        db_index=False,
    )
    occurred_at = models.DateTimeField(null=True, blank=True)
    provenance = models.CharField(max_length=24, choices=Provenance.choices)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_requesthistory_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(request_revision__gte=1),
                name="commercial_requesthistory_revision_positive",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["cutover_state", "created", "updated", "status_changed"]),
                name="commercial_requesthistory_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[value for value, _ in EventRequest.Status.choices]),
                name="commercial_requesthistory_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(provenance__in=["cutover_snapshot", "database"]),
                name="commercial_requesthistory_provenance_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_request_id}@{self.kind}"


class QuotationSequence(TenantModel):
    year = models.PositiveSmallIntegerField()
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_quote_sequence_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "year"], name="commercial_quote_sequence_org_year_uq"
            ),
            models.CheckConstraint(
                condition=Q(next_value__gte=1), name="commercial_quote_sequence_next_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}@{self.year}"


class Quotation(TenantModel):
    event_request = models.OneToOneField(
        EventRequest, on_delete=models.PROTECT, related_name="quotation", db_index=False
    )
    visible_number = models.CharField(max_length=24)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_quotation_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "event_request"], name="commercial_quotation_org_request_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "visible_number"], name="commercial_quotation_org_number_uq"
            ),
        ]

    def __str__(self) -> str:
        return self.visible_number


class QuotationVersion(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        ISSUED = "issued", "Emitida"
        ACCEPTED = "accepted", "Aceptada"
        SUPERSEDED = "superseded", "Sustituida"
        WITHDRAWN = "withdrawn", "Retirada"

    quotation = models.ForeignKey(
        Quotation, on_delete=models.PROTECT, related_name="versions", db_index=False
    )
    version = models.PositiveIntegerField()
    request_revision = models.PositiveIntegerField()
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    valid_until = models.DateTimeField()
    currency = models.CharField(max_length=3, default="USD")
    organization_name_snapshot = models.CharField(max_length=150)
    person_name_snapshot = models.CharField(max_length=150)
    person_phone_snapshot = models.CharField(max_length=13)
    person_email_snapshot = models.EmailField(max_length=254, blank=True)
    event_type_definition_snapshot = models.ForeignKey(
        EventType, on_delete=models.PROTECT, related_name="quotation_snapshots", db_index=False
    )
    event_type_snapshot = models.CharField(max_length=100)
    venue_snapshot = models.ForeignKey(
        Venue, on_delete=models.PROTECT, related_name="quotation_snapshots", db_index=False
    )
    venue_name_snapshot = models.CharField(max_length=150)
    space_snapshot = models.ForeignKey(
        Space, on_delete=models.PROTECT, related_name="quotation_snapshots", db_index=False
    )
    space_name_snapshot = models.CharField(max_length=150)
    event_starts_at_snapshot = models.DateTimeField()
    event_ends_at_snapshot = models.DateTimeField()
    event_timezone_snapshot = models.CharField(max_length=64)
    estimated_guests_snapshot = models.PositiveIntegerField()
    general_need_snapshot = models.CharField(max_length=500)
    request_notes_snapshot = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issued_quotation_versions",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accepted_quotation_versions",
    )
    acceptance_channel = models.CharField(max_length=32, blank=True)
    acceptance_note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_quoteversion_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "quotation", "version"],
                name="commercial_quoteversion_org_quote_version_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "quotation"],
                condition=Q(status="draft"),
                name="commercial_quoteversion_one_draft_uq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1) & Q(request_revision__gte=1) & Q(revision__gte=1),
                name="commercial_quoteversion_revisions_positive",
            ),
            models.CheckConstraint(
                condition=Q(currency="USD"), name="commercial_quoteversion_currency_usd"
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0)
                & Q(discount_total__gte=0)
                & Q(total__gte=0)
                & Q(discount_total__lte=F("subtotal"))
                & Q(total=F("subtotal") - F("discount_total")),
                name="commercial_quoteversion_totals_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quotation_id}@v{self.version}"


class QuotationLine(TenantModel):
    class Source(models.TextChoices):
        AD_HOC = "ad_hoc", "Línea ad hoc"
        CATALOG = "catalog", "Catálogo"

    quotation_version = models.ForeignKey(
        QuotationVersion, on_delete=models.PROTECT, related_name="lines", db_index=False
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.AD_HOC)
    catalog_item_revision = models.ForeignKey(
        CatalogItemRevision,
        on_delete=models.PROTECT,
        related_name="quotation_lines",
        null=True,
        blank=True,
        db_index=False,
    )
    catalog_price = models.ForeignKey(
        CatalogPrice,
        on_delete=models.PROTECT,
        related_name="quotation_lines",
        null=True,
        blank=True,
        db_index=False,
    )
    package_components_snapshot = models.JSONField(default=list)
    position = models.PositiveIntegerField()
    description = models.CharField(max_length=240)
    unit_label = models.CharField(max_length=40, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    line_subtotal = models.DecimalField(max_digits=18, decimal_places=2)
    line_total = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_quoteline_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "quotation_version", "position"],
                name="commercial_quoteline_org_version_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1)
                & Q(quantity__gt=0)
                & Q(unit_price__gte=0)
                & Q(discount_amount__gte=0)
                & Q(line_subtotal__gte=0)
                & Q(line_total__gte=0)
                & Q(discount_amount__lte=F("line_subtotal"))
                & Q(line_total=F("line_subtotal") - F("discount_amount")),
                name="commercial_quoteline_amounts_valid",
            ),
            models.CheckConstraint(
                condition=Q(line_subtotal=Round(F("quantity") * F("unit_price"), precision=2)),
                name="commercial_quoteline_subtotal_product",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        source="ad_hoc",
                        catalog_item_revision__isnull=True,
                        catalog_price__isnull=True,
                        package_components_snapshot=[],
                    )
                    | Q(
                        source="catalog",
                        catalog_item_revision__isnull=False,
                        catalog_price__isnull=False,
                    )
                ),
                name="commercial_quoteline_source_coherent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quotation_version_id}@{self.position}"


# Compatibilidad de importación de 5.1/5.2. La clase se registra exclusivamente
# como scheduling.Reservation; commercial no declara un segundo modelo.
from claridez.scheduling.models import Reservation as Reservation  # noqa: E402
