from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Trim

from claridez.organizations.models import Membership, Organization


class ContactOrigin(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    PHONE_CALL = "phone_call", "Llamada"
    SOCIAL_NETWORK = "social_network", "Red social"
    REFERRAL = "referral", "Referido"
    WALK_IN = "walk_in", "Visita"
    WEBSITE = "website", "Sitio web"
    OTHER = "other", "Otro"


class Person(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    full_name = models.CharField(max_length=150)
    phone_e164 = models.CharField(max_length=13)
    email = models.EmailField(max_length=254, blank=True)
    origin = models.CharField(max_length=24, choices=ContactOrigin.choices)
    origin_detail = models.CharField(max_length=160, blank=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commercial_person"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_person_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "phone_e164"], name="commercial_person_org_phone_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=~Q(email=""),
                name="commercial_person_org_email_uq",
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
                condition=Q(email=Lower(Trim("email"))),
                name="commercial_person_email_canonical",
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


class PersonRevision(models.Model):
    class ActorKind(models.TextChoices):
        INTERNAL_USER = "internal_user", "Usuario interno"
        EXTERNAL_SUBJECT = "external_subject", "Titular externo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="revisions", db_index=False
    )
    revision = models.PositiveIntegerField()
    full_name = models.CharField(max_length=150)
    phone_e164 = models.CharField(max_length=13)
    email = models.EmailField(max_length=254, blank=True)
    origin = models.CharField(max_length=24, choices=ContactOrigin.choices)
    origin_detail = models.CharField(max_length=160, blank=True)
    actor_kind = models.CharField(
        max_length=20, choices=ActorKind.choices, default=ActorKind.INTERNAL_USER
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    external_evidence_reference = models.CharField(max_length=240, blank=True)
    external_evidence_sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commercial_personrevision"
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
            models.CheckConstraint(
                condition=(
                    Q(
                        actor_kind="internal_user",
                        changed_by__isnull=False,
                        external_evidence_reference="",
                        external_evidence_sha256="",
                    )
                    | (
                        Q(
                            actor_kind="external_subject",
                            changed_by__isnull=True,
                            external_evidence_reference=Trim("external_evidence_reference"),
                            external_evidence_sha256__regex=r"^[0-9a-f]{64}$",
                        )
                        & ~Q(external_evidence_reference="")
                    )
                ),
                name="commercial_personrevision_actor_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.person_id}@{self.revision}"


class PersonMerge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    source_person = models.OneToOneField(
        Person, on_delete=models.PROTECT, related_name="merge_as_source", db_index=False
    )
    target_person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="merge_sources", db_index=False
    )
    source_revision = models.PositiveIntegerField()
    target_revision = models.PositiveIntegerField()
    reason = models.CharField(max_length=500)
    idempotency_key = models.UUIDField()
    merged_by_membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="person_merges", db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="people_personmerge_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "source_person"],
                name="people_personmerge_org_source_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="people_personmerge_org_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=~Q(source_person=models.F("target_person")),
                name="people_personmerge_distinct_people",
            ),
            models.CheckConstraint(
                condition=Q(source_revision__gte=1) & Q(target_revision__gte=1),
                name="people_personmerge_revisions_positive",
            ),
            models.CheckConstraint(
                condition=Q(reason=Trim("reason")) & ~Q(reason=""),
                name="people_personmerge_reason_canonical",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_person_id}->{self.target_person_id}"


class PersonContactAlias(models.Model):
    class Kind(models.TextChoices):
        PHONE = "phone", "Teléfono"
        EMAIL = "email", "Correo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="contact_aliases", db_index=False
    )
    source_person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="provided_contact_aliases", db_index=False
    )
    source_revision = models.PositiveIntegerField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    normalized_value = models.CharField(max_length=254)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="people_contactalias_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "kind", "normalized_value"],
                name="people_contactalias_org_kind_value_uq",
            ),
            models.CheckConstraint(
                condition=Q(source_revision__gte=1),
                name="people_contactalias_revision_positive",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["phone", "email"]),
                name="people_contactalias_kind_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="phone",
                        normalized_value__regex=r"^\+593(?:[2-7][0-9]{7}|9[0-9]{8})$",
                    )
                    | (
                        Q(kind="email", normalized_value=Lower(Trim("normalized_value")))
                        & ~Q(normalized_value="")
                    )
                ),
                name="people_contactalias_value_canonical",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.normalized_value}"


class ConsentEvent(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Correo"
        WHATSAPP = "whatsapp", "WhatsApp"
        PHONE = "phone", "Teléfono"
        OTHER = "other", "Otro"

    class EventType(models.TextChoices):
        GRANT = "grant", "Concesión"
        REVOKE = "revoke", "Revocación"
        CORRECTION = "correction", "Rectificación"

    class Decision(models.TextChoices):
        GRANTED = "granted", "Concedido"
        REVOKED = "revoked", "Revocado"

    class RecorderKind(models.TextChoices):
        INTERNAL_MEMBERSHIP = "internal_membership", "Membresía interna"
        EXTERNAL_SUBJECT = "external_subject", "Titular externo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="consent_events", db_index=False
    )
    purpose = models.CharField(max_length=80)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    decision = models.CharField(max_length=16, choices=Decision.choices)
    source = models.CharField(max_length=80)
    occurred_at = models.DateTimeField()
    evidence_reference = models.CharField(max_length=240)
    corrects = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    recorder_kind = models.CharField(
        max_length=24, choices=RecorderKind.choices, default=RecorderKind.INTERNAL_MEMBERSHIP
    )
    recorded_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="recorded_consents",
        db_index=False,
        null=True,
        blank=True,
    )
    external_submission_reference = models.CharField(max_length=240, blank=True)
    external_evidence_sha256 = models.CharField(max_length=64, blank=True)
    observed_text_sha256 = models.CharField(max_length=64, blank=True)
    presentation_version = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="people_consentevent_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(purpose=Trim("purpose")) & ~Q(purpose=""),
                name="people_consentevent_purpose_canonical",
            ),
            models.CheckConstraint(
                condition=Q(source=Trim("source")) & ~Q(source=""),
                name="people_consentevent_source_canonical",
            ),
            models.CheckConstraint(
                condition=Q(evidence_reference=Trim("evidence_reference"))
                & ~Q(evidence_reference=""),
                name="people_consentevent_evidence_canonical",
            ),
            models.CheckConstraint(
                condition=Q(channel__in=["email", "whatsapp", "phone", "other"]),
                name="people_consentevent_channel_valid",
            ),
            models.CheckConstraint(
                condition=Q(event_type__in=["grant", "revoke", "correction"]),
                name="people_consentevent_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(decision__in=["granted", "revoked"]),
                name="people_consentevent_decision_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        recorder_kind="internal_membership",
                        recorded_by_membership__isnull=False,
                        external_submission_reference="",
                        external_evidence_sha256="",
                        observed_text_sha256="",
                        presentation_version="",
                    )
                    | (
                        Q(
                            recorder_kind="external_subject",
                            recorded_by_membership__isnull=True,
                            external_submission_reference=Trim("external_submission_reference"),
                            external_evidence_sha256__regex=r"^[0-9a-f]{64}$",
                            observed_text_sha256__regex=r"^[0-9a-f]{64}$",
                            presentation_version=Trim("presentation_version"),
                        )
                        & ~Q(external_submission_reference="")
                        & ~Q(presentation_version="")
                    )
                ),
                name="people_consentevent_recorder_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.person_id}@{self.purpose}:{self.channel}"
