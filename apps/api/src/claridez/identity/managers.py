"""Manager y normalización canónica para el usuario local."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:
    from .models import User


def canonicalize_email(email: str | None) -> str:
    """Aplicar la única representación de correo admitida por Claridez."""
    if email is None:
        raise ValueError("El correo es obligatorio.")
    canonical_email = email.strip().lower()
    if not canonical_email:
        raise ValueError("El correo es obligatorio.")
    return canonical_email


class UserManager(BaseUserManager["User"]):
    """Crear usuarios con correo y estado canónicos."""

    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        """Normalizar la dirección completa, no solo el dominio."""
        return canonicalize_email(email)

    def get_by_natural_key(self, username: str | None) -> User:
        """Resolver la identidad con la misma representación canónica del correo."""
        canonical_email = self.normalize_email(username)
        return self.get(**{self.model.USERNAME_FIELD: canonical_email})

    def _create_user(
        self,
        email: str,
        password: str | None,
        **extra_fields: Any,
    ) -> User:
        canonical_email = self.normalize_email(email)
        status = extra_fields.setdefault(
            "status",
            self.model.Status.PENDING_VERIFICATION,
        )
        expected_is_active = status == self.model.Status.ACTIVE
        if "is_active" in extra_fields and bool(extra_fields["is_active"]) != expected_is_active:
            raise ValueError("status e is_active son contradictorios.")
        extra_fields["is_active"] = expected_is_active

        user = self.model(email=canonical_email, **extra_fields)
        user.set_password(password)
        user.full_clean(validate_unique=False, validate_constraints=False)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Crear un usuario local sin privilegios implícitos."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Crear un superusuario técnico activo, sin rol de producto."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("status", self.model.Status.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")
        if extra_fields.get("status") != self.model.Status.ACTIVE:
            raise ValueError("Un superusuario debe tener status=active.")

        return self._create_user(email, password, **extra_fields)
