"""Servicios transaccionales de organizaciones y membresías."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from claridez.identity.managers import canonicalize_email
from claridez.identity.models import User

from .exceptions import (
    BootstrapConflict,
    InvalidMembershipRoleChange,
    InvalidMembershipTransition,
    InvalidOrganizationTransition,
    LastActiveOwnerRequired,
    MembershipAlreadyExists,
    MembershipNotFound,
    OrganizationNotFound,
    OrganizationSlugConflict,
    UserNotActive,
)
from .models import Membership, Organization, OrganizationSettings, Space, Venue
from .normalization import canonicalize_organization_name, canonicalize_organization_slug

BOOTSTRAP_ADVISORY_LOCK_KEY = int.from_bytes(b"CLARIDEZ", byteorder="big", signed=False)


@dataclass(frozen=True, slots=True)
class OrganizationCreation:
    organization: Organization
    owner_membership: Membership


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    organization: Organization
    owner_membership: Membership
    user: User
    created: bool


def _constraint_name(error: IntegrityError) -> str | None:
    cause = error.__cause__
    diagnostics = getattr(cause, "diag", None)
    value = getattr(diagnostics, "constraint_name", None)
    return value if isinstance(value, str) else None


def _require_active_user(user: User) -> None:
    if user.status != User.Status.ACTIVE or not bool(user.is_active):
        raise UserNotActive("El usuario debe estar activo.")


def _lock_organization(organization_id: UUID) -> Organization:
    try:
        return Organization.objects.select_for_update().get(pk=organization_id)
    except Organization.DoesNotExist as error:
        raise OrganizationNotFound("La organización no existe.") from error


def _lock_membership(organization: Organization, membership_id: UUID) -> Membership:
    try:
        return Membership.objects.select_for_update().get(
            pk=membership_id,
            organization=organization,
        )
    except Membership.DoesNotExist as error:
        raise MembershipNotFound("La membresía no existe.") from error


def _has_active_owner_after(
    organization: Organization,
    *,
    membership: Membership | None = None,
    role: Membership.Role | str | None = None,
    status: Membership.Status | str | None = None,
) -> bool:
    owners = Membership.objects.filter(
        organization=organization,
        role=Membership.Role.OWNER,
        status=Membership.Status.ACTIVE,
    )
    if membership is not None:
        owners = owners.exclude(pk=membership.pk)
        prospective_role = role if role is not None else membership.role
        prospective_status = status if status is not None else membership.status
        target_is_owner = (
            prospective_role == Membership.Role.OWNER
            and prospective_status == Membership.Status.ACTIVE
        )
    else:
        target_is_owner = role == Membership.Role.OWNER and status == Membership.Status.ACTIVE
    return target_is_owner or owners.exists()


def create_organization(
    *,
    owner_user_id: UUID,
    name: str,
    slug: str | None = None,
) -> OrganizationCreation:
    """Crear una organización activa y su primer propietario como una sola unidad."""
    canonical_name = canonicalize_organization_name(name)
    canonical_slug = canonicalize_organization_slug(slug if slug is not None else canonical_name)

    try:
        with transaction.atomic():
            try:
                owner = User.objects.select_for_update().get(pk=owner_user_id)
            except User.DoesNotExist as error:
                raise UserNotActive("El usuario propietario no existe.") from error
            _require_active_user(owner)

            organization = Organization(
                name=canonical_name,
                slug=canonical_slug,
                status=Organization.Status.ACTIVE,
            )
            organization.full_clean(validate_unique=False, validate_constraints=False)
            organization.save()

            owner_membership = Membership(
                organization=organization,
                user=owner,
                role=Membership.Role.OWNER,
                status=Membership.Status.ACTIVE,
                joined_at=timezone.now(),
            )
            owner_membership.full_clean(validate_unique=False, validate_constraints=False)
            owner_membership.save()

            from .capabilities import Capability
            from .tenant_scope import authorized_tenant_scope

            with authorized_tenant_scope(
                owner,
                organization.pk,
                Capability.BUSINESS_CONFIGURATION_MANAGE,
            ):
                OrganizationSettings.objects.create(organization=organization)
                venue = Venue.objects.create(
                    organization=organization,
                    name="Sede principal",
                    location_reference="",
                    is_primary=True,
                    is_active=True,
                )
                Space.objects.create(
                    organization=organization,
                    venue=venue,
                    name="Espacio principal",
                    is_primary=True,
                    is_active=True,
                )
            return OrganizationCreation(organization, owner_membership)
    except IntegrityError as error:
        if _constraint_name(error) == "organizations_organization_slug_unique":
            raise OrganizationSlugConflict(
                "El slug de la organización no está disponible."
            ) from error
        raise


def rename_organization(*, organization_id: UUID, name: str) -> Organization:
    """Cambiar únicamente el nombre visible; el slug permanece estable."""
    canonical_name = canonicalize_organization_name(name)
    with transaction.atomic():
        organization = _lock_organization(organization_id)
        organization.name = canonical_name
        organization.save(update_fields=["name", "updated_at"])
        return organization


def transition_organization(
    *,
    organization_id: UUID,
    target_status: Organization.Status | str,
) -> Organization:
    """Aplicar una transición explícita de estado organizacional."""
    try:
        canonical_status = Organization.Status(target_status)
    except ValueError as error:
        raise InvalidOrganizationTransition("Estado de organización no reconocido.") from error

    with transaction.atomic():
        organization = _lock_organization(organization_id)
        current_status = Organization.Status(organization.status)
        allowed: dict[Organization.Status, Organization.Status] = {
            Organization.Status.ACTIVE: Organization.Status.SUSPENDED,
            Organization.Status.SUSPENDED: Organization.Status.ACTIVE,
        }
        if allowed.get(current_status) != canonical_status:
            raise InvalidOrganizationTransition("Transición de organización no permitida.")
        if not _has_active_owner_after(organization):
            raise LastActiveOwnerRequired("La organización requiere un propietario activo.")
        organization.status = canonical_status
        organization.save(update_fields=["status", "updated_at"])
        return organization


def add_membership(
    *,
    organization_id: UUID,
    user_id: UUID,
    role: Membership.Role | str,
) -> Membership:
    """Añadir una relación activa sin crear duplicados históricos."""
    try:
        canonical_role = Membership.Role(role)
    except ValueError as error:
        raise InvalidMembershipRoleChange("Rol de membresía no reconocido.") from error

    try:
        with transaction.atomic():
            organization = _lock_organization(organization_id)
            try:
                user = User.objects.select_for_update().get(pk=user_id)
            except User.DoesNotExist as error:
                raise UserNotActive("El usuario no existe.") from error
            _require_active_user(user)
            if not _has_active_owner_after(
                organization,
                role=canonical_role,
                status=Membership.Status.ACTIVE,
            ):
                raise LastActiveOwnerRequired("La organización requiere un propietario activo.")
            membership = Membership(
                organization=organization,
                user=user,
                role=canonical_role,
                status=Membership.Status.ACTIVE,
                joined_at=timezone.now(),
            )
            membership.full_clean(validate_unique=False, validate_constraints=False)
            membership.save()
            return membership
    except IntegrityError as error:
        if _constraint_name(error) == "organizations_membership_org_user_unique":
            raise MembershipAlreadyExists(
                "El usuario ya tiene una relación con la organización."
            ) from error
        raise


def change_membership_role(
    *,
    organization_id: UUID,
    membership_id: UUID,
    target_role: Membership.Role | str,
) -> Membership:
    """Cambiar un rol bajo el bloqueo único de la organización."""
    try:
        canonical_role = Membership.Role(target_role)
    except ValueError as error:
        raise InvalidMembershipRoleChange("Rol de membresía no reconocido.") from error

    with transaction.atomic():
        organization = _lock_organization(organization_id)
        membership = _lock_membership(organization, membership_id)
        if membership.status == Membership.Status.REVOKED:
            raise InvalidMembershipRoleChange("Una membresía revocada no cambia de rol.")
        if membership.role == canonical_role:
            raise InvalidMembershipRoleChange("La membresía ya tiene ese rol.")
        if not _has_active_owner_after(
            organization,
            membership=membership,
            role=canonical_role,
        ):
            raise LastActiveOwnerRequired("No se puede retirar al último propietario activo.")
        membership.role = canonical_role
        membership.save(update_fields=["role", "updated_at"])
        return membership


def transition_membership(
    *,
    organization_id: UUID,
    membership_id: UUID,
    target_status: Membership.Status | str,
) -> Membership:
    """Suspender, revocar o reactivar una membresía persistente."""
    try:
        canonical_status = Membership.Status(target_status)
    except ValueError as error:
        raise InvalidMembershipTransition("Estado de membresía no reconocido.") from error

    with transaction.atomic():
        organization = _lock_organization(organization_id)
        membership = _lock_membership(organization, membership_id)
        current_status = Membership.Status(membership.status)
        allowed: dict[Membership.Status, set[Membership.Status]] = {
            Membership.Status.ACTIVE: {
                Membership.Status.SUSPENDED,
                Membership.Status.REVOKED,
            },
            Membership.Status.SUSPENDED: {
                Membership.Status.ACTIVE,
                Membership.Status.REVOKED,
            },
            Membership.Status.REVOKED: {Membership.Status.ACTIVE},
        }
        if canonical_status not in allowed[current_status]:
            raise InvalidMembershipTransition("Transición de membresía no permitida.")

        if canonical_status == Membership.Status.ACTIVE:
            try:
                user = User.objects.select_for_update().get(pk=membership.user_id)
            except User.DoesNotExist as error:
                raise UserNotActive("El usuario no existe.") from error
            _require_active_user(user)

        if not _has_active_owner_after(
            organization,
            membership=membership,
            status=canonical_status,
        ):
            raise LastActiveOwnerRequired("No se puede retirar al último propietario activo.")

        now = timezone.now()
        membership.status = canonical_status
        if canonical_status == Membership.Status.ACTIVE:
            membership.suspended_at = None
            membership.revoked_at = None
        elif canonical_status == Membership.Status.SUSPENDED:
            membership.suspended_at = now
            membership.revoked_at = None
        else:
            membership.revoked_at = now
        membership.save(update_fields=["status", "suspended_at", "revoked_at", "updated_at"])
        return membership


def revoke_membership_sessions(
    *,
    organization_id: UUID,
    membership_id: UUID,
) -> Membership:
    """Invalidar todas las sesiones del usuario respetando el orden de bloqueos."""
    with transaction.atomic():
        organization = _lock_organization(organization_id)
        membership = _lock_membership(organization, membership_id)
        try:
            user = User.objects.select_for_update().get(pk=membership.user_id)
        except User.DoesNotExist as error:
            raise UserNotActive("El usuario no existe.") from error
        user.security_version += 1
        user.save(update_fields=["security_version", "updated_at"])
        return membership


def _acquire_bootstrap_lock() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (BOOTSTRAP_ADVISORY_LOCK_KEY,))


def _require_reusable_bootstrap_user(user: User) -> None:
    try:
        _require_active_user(user)
    except UserNotActive as error:
        raise BootstrapConflict("El usuario existente no está activo.") from error
    if user.email_verified_at is None:
        raise BootstrapConflict("El usuario existente no tiene el correo verificado.")
    if not user.has_usable_password():
        raise BootstrapConflict("El usuario existente no tiene una contraseña utilizable.")


def _create_bootstrap_user(
    *,
    email: str,
    display_name: str | None,
    password: str | None,
) -> User:
    canonical_display_name = (display_name or "").strip()
    if not canonical_display_name:
        raise BootstrapConflict("El nombre visible es obligatorio para un usuario nuevo.")
    if len(canonical_display_name) > 150:
        raise BootstrapConflict("El nombre visible excede la longitud máxima.")
    if password is None:
        raise BootstrapConflict("La contraseña es obligatoria para un usuario nuevo.")

    user = User(
        email=email,
        display_name=canonical_display_name,
        status=User.Status.ACTIVE,
        is_active=True,
        is_staff=False,
        is_superuser=False,
        email_verified_at=timezone.now(),
    )
    validate_password(password, user=user)
    user.set_password(password)
    user.full_clean(validate_unique=False, validate_constraints=False)
    user.save()
    return user


def bootstrap_organization(
    *,
    email: str,
    organization_name: str,
    organization_slug: str | None,
    display_name: str | None = None,
    password: str | None = None,
) -> BootstrapResult:
    """Provisionar localmente usuario, organización y propietario de forma idempotente."""
    canonical_email = canonicalize_email(email)
    canonical_name = canonicalize_organization_name(organization_name)
    canonical_slug = canonicalize_organization_slug(
        organization_slug if organization_slug is not None else canonical_name
    )

    with transaction.atomic():
        _acquire_bootstrap_lock()
        existing_organization = Organization.objects.filter(slug=canonical_slug).first()

        if existing_organization is not None:
            organization = _lock_organization(existing_organization.pk)
            try:
                user_reference = User.objects.get(email=canonical_email)
            except User.DoesNotExist as error:
                raise BootstrapConflict(
                    "La organización existente no coincide con el propietario solicitado."
                ) from error
            try:
                membership = _lock_membership(
                    organization,
                    Membership.objects.only("pk")
                    .get(organization=organization, user=user_reference)
                    .pk,
                )
            except Membership.DoesNotExist as error:
                raise BootstrapConflict(
                    "La organización existente no coincide con el propietario solicitado."
                ) from error
            user = User.objects.select_for_update().get(pk=user_reference.pk)
            _require_reusable_bootstrap_user(user)
            if organization.status != Organization.Status.ACTIVE:
                raise BootstrapConflict("La organización existente no está activa.")
            if (
                membership.role != Membership.Role.OWNER
                or membership.status != Membership.Status.ACTIVE
            ):
                raise BootstrapConflict("La relación existente no es una propiedad activa.")
            return BootstrapResult(organization, membership, user, created=False)

        existing_user = User.objects.filter(email=canonical_email).first()
        if existing_user is None:
            user = _create_bootstrap_user(
                email=canonical_email,
                display_name=display_name,
                password=password,
            )
        else:
            if display_name is not None or password is not None:
                raise BootstrapConflict(
                    "El usuario cambió durante el bootstrap; vuelva a intentar."
                )
            user = User.objects.select_for_update().get(pk=existing_user.pk)
            _require_reusable_bootstrap_user(user)

        creation = create_organization(
            owner_user_id=user.pk,
            name=canonical_name,
            slug=canonical_slug,
        )
        return BootstrapResult(
            creation.organization,
            creation.owner_membership,
            user,
            created=True,
        )
