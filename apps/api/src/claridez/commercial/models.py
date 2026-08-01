from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Trim

from claridez.organizations.models import Membership, Organization


class ContactOrigin(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    PHONE_CALL = "phone_call", "Llamada"
    SOCIAL_NETWORK = "social_network", "Red social"
    REFERRAL = "referral", "Referido"
    WALK_IN = "walk_in", "Visita"
    WEBSITE = "website", "Sitio web"
    OTHER = "other", "Otro"


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Person(TenantModel):
    full_name = models.CharField(max_length=150)
    phone_e164 = models.CharField(max_length=13)
    email = models.EmailField(max_length=254, blank=True)
    origin = models.CharField(max_length=24, choices=ContactOrigin.choices)
    origin_detail = models.CharField(max_length=160, blank=True)
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_person_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "phone_e164"], name="commercial_person_org_phone_uq"
            ),
            models.CheckConstraint(
                condition=Q(full_name=Trim("full_name")) & ~Q(full_name=""),
                name="commercial_person_name_canonical",
            ),
            models.CheckConstraint(
                condition=Q(phone_e164__regex=r"^\+593(?:[2-7][0-9]{7}|9[0-9]{8})$"),
                name="commercial_person_phone_ec",
            ),
            models.CheckConstraint(
                condition=Q(origin__in=[value for value, _ in ContactOrigin.choices]),
                name="commercial_person_origin_valid",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="commercial_person_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.full_name


class PersonRevision(TenantModel):
    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="revisions", db_index=False
    )
    revision = models.PositiveIntegerField()
    full_name = models.CharField(max_length=150)
    phone_e164 = models.CharField(max_length=13)
    email = models.EmailField(max_length=254, blank=True)
    origin = models.CharField(max_length=24, choices=ContactOrigin.choices)
    origin_detail = models.CharField(max_length=160, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_personrevision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "person", "revision"],
                name="commercial_personrevision_org_person_rev_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="commercial_personrevision_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.person_id}@{self.revision}"


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
    event_type_snapshot = models.CharField(max_length=100)
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
    quotation_version = models.ForeignKey(
        QuotationVersion, on_delete=models.PROTECT, related_name="lines", db_index=False
    )
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
        ]

    def __str__(self) -> str:
        return f"{self.quotation_version_id}@{self.position}"


class Reservation(TenantModel):
    class Status(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        CONFIRMED = "confirmed", "Confirmada"
        EXPIRED = "expired", "Vencida"
        CANCELLED = "cancelled", "Cancelada"

    class ConfirmationKind(models.TextChoices):
        EXTERNAL_DEPOSIT = "external_deposit", "Anticipo recibido externamente"
        WAIVER = "waiver", "Excepción autorizada"

    event_request = models.ForeignKey(
        EventRequest, on_delete=models.PROTECT, related_name="reservations", db_index=False
    )
    quotation_version = models.OneToOneField(
        QuotationVersion, on_delete=models.PROTECT, related_name="reservation", db_index=False
    )
    event_interval = DateTimeRangeField()
    event_timezone = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROVISIONAL)
    hold_expires_at = models.DateTimeField()
    confirmation_kind = models.CharField(
        max_length=24, choices=ConfirmationKind.choices, blank=True
    )
    recognized_deposit_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    deposit_reported_at = models.DateTimeField(null=True, blank=True)
    deposit_reference = models.CharField(max_length=300, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confirmed_reservations",
    )
    waiver_reason = models.CharField(max_length=500, blank=True)
    waiver_authorized_at = models.DateTimeField(null=True, blank=True)
    waiver_authorized_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="waived_reservation_deposits",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_reservations",
    )
    cancellation_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_reservation_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "quotation_version"],
                name="commercial_reservation_org_quoteversion_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "event_request"],
                condition=Q(status__in=["provisional", "confirmed"]),
                name="commercial_reservation_one_active_request_uq",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["provisional", "confirmed", "expired", "cancelled"]),
                name="commercial_reservation_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(recognized_deposit_amount__isnull=True)
                | Q(recognized_deposit_amount__gt=0),
                name="commercial_reservation_deposit_positive",
            ),
            ExclusionConstraint(
                name="commercial_reservation_no_overlap",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("event_interval", RangeOperators.OVERLAPS),
                ],
                condition=Q(status__in=["provisional", "confirmed"]),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_request_id}@{self.status}"
