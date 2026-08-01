"""Modelos globales de organizaciones y membresías."""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models.functions import Trim
from django.utils import timezone

from .normalization import (
    MAX_ORGANIZATION_NAME_LENGTH,
    MAX_ORGANIZATION_SLUG_LENGTH,
    MAX_TIMEZONE_LENGTH,
    PostgreSQLTimezoneIsValid,
    canonicalize_currency,
    canonicalize_organization_name,
    canonicalize_organization_slug,
    canonicalize_timezone,
    validate_iana_timezone,
)


class Organization(models.Model):
    """Límite organizacional global y pivote de bloqueos concurrentes."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Activa"
        SUSPENDED = "suspended", "Suspendida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=MAX_ORGANIZATION_NAME_LENGTH)
    slug = models.SlugField(max_length=MAX_ORGANIZATION_SLUG_LENGTH, db_index=False)
    status = models.CharField(max_length=16, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name="") & models.Q(name=Trim("name")),
                name="organizations_organization_name_canonical",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(slug__regex=r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$")
                    & ~models.Q(slug__contains="--")
                ),
                name="organizations_organization_slug_canonical",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                name="organizations_organization_slug_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "suspended"]),
                name="organizations_organization_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persistir nombre y slug canónicos."""
        self.name = canonicalize_organization_name(self.name)
        self.slug = canonicalize_organization_slug(self.slug)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Aplicar la representación canónica antes de validar el modelo."""
        self.name = canonicalize_organization_name(self.name)
        self.slug = canonicalize_organization_slug(self.slug)
        super().clean()


class Membership(models.Model):
    """Relación persistente entre un usuario y una organización."""

    class Role(models.TextChoices):
        OWNER = "owner", "Propietario"
        ADMINISTRATOR = "administrator", "Administrador"
        COMMERCIAL = "commercial", "Comercial"
        OPERATIONS = "operations", "Operaciones"
        FINANCE = "finance", "Finanzas"

    class Status(models.TextChoices):
        ACTIVE = "active", "Activa"
        SUSPENDED = "suspended", "Suspendida"
        REVOKED = "revoked", "Revocada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="memberships",
        db_index=False,
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    joined_at = models.DateTimeField(default=timezone.now, editable=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="organizations_membership_org_user_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    role__in=["owner", "administrator", "commercial", "operations", "finance"]
                ),
                name="organizations_membership_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "suspended", "revoked"]),
                name="organizations_membership_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="active",
                        suspended_at__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | models.Q(
                        status="suspended",
                        suspended_at__isnull=False,
                        revoked_at__isnull=True,
                    )
                    | models.Q(status="revoked", revoked_at__isnull=False)
                ),
                name="organizations_membership_status_dates_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(suspended_at__isnull=True) | models.Q(suspended_at__gte=F("joined_at"))
                ),
                name="organizations_membership_suspended_after_joined",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True) | models.Q(revoked_at__gte=F("joined_at"))
                ),
                name="organizations_membership_revoked_after_joined",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization"],
                condition=models.Q(role="owner", status="active"),
                name="organizations_active_owner_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.organization_id}"


class OrganizationSettings(models.Model):
    """Configuración privada y tenant-aware de una organización."""

    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        related_name="settings",
        primary_key=True,
    )
    currency = models.CharField(max_length=3, default="USD")
    timezone = models.CharField(
        max_length=MAX_TIMEZONE_LENGTH,
        default="America/Guayaquil",
        validators=[validate_iana_timezone],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "organization settings"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(currency__regex=r"^[A-Z]{3}$"),
                name="organizations_settings_currency_canonical",
            ),
            models.CheckConstraint(
                condition=~models.Q(timezone="") & models.Q(timezone=Trim("timezone")),
                name="organizations_settings_timezone_canonical",
            ),
            models.CheckConstraint(
                condition=PostgreSQLTimezoneIsValid(F("timezone")),
                name="organizations_settings_timezone_iana_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"settings@{self.organization_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.currency = canonicalize_currency(self.currency)
        self.timezone = canonicalize_timezone(self.timezone)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        self.currency = canonicalize_currency(self.currency)
        self.timezone = canonicalize_timezone(self.timezone)
        super().clean()
