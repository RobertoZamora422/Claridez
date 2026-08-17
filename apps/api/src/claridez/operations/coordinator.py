"""Compatibilidad 5.2: scheduling coordina ahora la transacción transversal."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from claridez.application.reservation_confirmation import confirm_reservation
from claridez.identity.models import User
from claridez.scheduling.public import cancel_command


def confirm_reservation_with_operations(
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
    return confirm_reservation(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        kind=kind,
        recognized_amount=recognized_amount,
        reported_at=reported_at,
        reference=reference,
        waiver_reason=waiver_reason,
    )


def cancel_reservation_with_operations(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    return cancel_command(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        reason=reason,
    )
