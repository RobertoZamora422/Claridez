from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from claridez.identity.models import User
from claridez.scheduling.public import legacy_availability_command

from .scheduling_adapter import scheduling_call


def list_availability(
    actor: User,
    organization_reference: UUID | str,
    *,
    space_id: UUID | str,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, Any]:
    return scheduling_call(
        legacy_availability_command,
        actor,
        organization_reference,
        space_id=space_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
