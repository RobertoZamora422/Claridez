"""Adaptadores compatibles 5.1 sobre la autoridad pública de scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope
from claridez.scheduling.public import (
    cancel_command,
    confirm_command,
    expire_overdue_for_organization,
    read_command,
)

from .scheduling_adapter import scheduling_call

HOLD_DURATION = timedelta(hours=48)


def _expire_overdue(authorization: TenantAuthorization, *, now: datetime | None = None) -> int:
    del now
    return expire_overdue_for_organization(authorization)


def _evaluate_expiration(
    actor: User,
    organization_reference: UUID | str,
    capability: Capability,
) -> int:
    with authorized_tenant_scope(actor, organization_reference, capability) as authorization:
        return expire_overdue_for_organization(authorization)


def read_reservation(
    actor: User, organization_reference: UUID | str, *, reservation_id: UUID | str
) -> dict[str, Any]:
    return scheduling_call(
        read_command,
        actor,
        organization_reference,
        reservation_id=reservation_id,
    )


def confirm_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    kind: str,
    recognized_amount: Decimal | None = None,
    reported_at: datetime | None = None,
    reference: str = "",
    waiver_reason: str = "",
) -> dict[str, Any]:
    return scheduling_call(
        confirm_command,
        actor,
        organization_reference,
        reservation_id=reservation_id,
        kind=kind,
        recognized_amount=recognized_amount,
        reported_at=reported_at,
        reference=reference,
        waiver_reason=waiver_reason,
    )


def cancel_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    return scheduling_call(
        cancel_command,
        actor,
        organization_reference,
        reservation_id=reservation_id,
        reason=reason,
    )
