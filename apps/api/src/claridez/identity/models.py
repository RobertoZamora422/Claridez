"""Modelo productivo del usuario global de Claridez."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower, Trim
from django.utils.crypto import salted_hmac

from .managers import UserManager, canonicalize_email


class User(AbstractUser):
    """Identidad local global, independiente de organizaciones y proveedores."""

    class Status(models.TextChoices):
        PENDING_VERIFICATION = "pending_verification", "Pendiente de verificación"
        ACTIVE = "active", "Activo"
        SUSPENDED = "suspended", "Suspendido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None  # type: ignore[assignment]
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]
    date_joined = None  # type: ignore[assignment]
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_VERIFICATION,
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    security_version = models.BigIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ClassVar[UserManager] = UserManager()  # type: ignore[assignment]

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(email="") & models.Q(email=Lower(Trim("email"))),
                name="identity_user_email_canonical",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="active", is_active=True)
                    | models.Q(
                        status__in=["pending_verification", "suspended"],
                        is_active=False,
                    )
                ),
                name="identity_user_status_active_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(security_version__gte=1),
                name="identity_user_security_version_positive",
            ),
        ]

    def clean(self) -> None:
        """Normalizar el correo antes de ejecutar validaciones de modelo."""
        self.email = canonicalize_email(self.email)
        super().clean()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persistir siempre la representación canónica del correo."""
        self.email = canonicalize_email(self.email)
        super().save(*args, **kwargs)

    def set_status(self, status: Status | str) -> None:
        """Cambiar conjuntamente el estado de dominio y la proyección Django."""
        try:
            canonical_status = self.Status(status)
        except ValueError as error:
            raise ValueError("Estado de usuario no reconocido.") from error
        self.status = canonical_status
        self.is_active = canonical_status == self.Status.ACTIVE

    def get_full_name(self) -> str:
        """Devolver el único nombre de usuario definido por Claridez."""
        return self.display_name

    def get_short_name(self) -> str:
        """Devolver el mismo nombre visible sin alternativas implícitas."""
        return self.display_name

    def _get_session_auth_hash(self, secret: str | None = None) -> str:
        """Incluir identidad y versión de seguridad preservando los fallbacks de Django."""
        key_salt = "claridez.identity.models.User.get_session_auth_hash"
        value = f"{self.pk}:{self.password}:{self.security_version}"
        return salted_hmac(
            key_salt,
            value,
            secret=secret,
            algorithm="sha256",
        ).hexdigest()
