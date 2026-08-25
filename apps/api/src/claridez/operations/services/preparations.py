from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

from ..errors import conflict, invalid
from ..models import EventPreparation
from ..normalization import canonical_optional_text
from ..representations import preparation_representation
from .shared import (
    EDITABLE_PREPARATION_STATES,
    check_revision,
    eligible_membership,
    get_preparation,
    increment_preparation,
)


def update_preparation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    operational_notes: str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status not in EDITABLE_PREPARATION_STATES:
            raise conflict("invalid_transition", "La preparación ya no puede editarse.")
        check_revision(preparation, revision)
        try:
            notes = canonical_optional_text(
                operational_notes, field="Las notas operativas", max_length=4000
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        if preparation.operational_notes != notes:
            preparation.operational_notes = notes
            increment_preparation(preparation, fields=["operational_notes"])
        return preparation_representation(
            get_preparation(authorization.organization_id, reservation_id),
            now=timezone.now(),
            include_items=True,
        )


def assign_preparation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    responsible_membership_id: UUID | str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status in {
            EventPreparation.Status.COMPLETED,
            EventPreparation.Status.CANCELLED,
        }:
            raise conflict("invalid_transition", "La preparación ya no puede asignarse.")
        check_revision(preparation, revision)
        responsible = eligible_membership(authorization.organization_id, responsible_membership_id)
        if preparation.responsible_membership_id != responsible.pk:
            preparation.responsible_membership = responsible
            increment_preparation(preparation, fields=["responsible_membership"])
        return preparation_representation(
            get_preparation(authorization.organization_id, reservation_id),
            now=timezone.now(),
            include_items=True,
        )
