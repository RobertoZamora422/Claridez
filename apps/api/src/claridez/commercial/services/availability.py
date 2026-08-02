from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.range import Range

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.models import Space
from claridez.organizations.tenant_scope import authorized_tenant_scope

from ..models import Reservation
from .representations import _reservation_summary
from .reservations import _expire_overdue
from .shared import _uuid, _validate_interval


def list_availability(
    actor: User,
    organization_reference: UUID | str,
    *,
    space_id: UUID | str,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as authorization:
        start, end = _validate_interval(starts_at, ends_at)
        try:
            space = Space.objects.select_related("venue").get(
                organization_id=authorization.organization_id,
                pk=_uuid(space_id, "El espacio"),
                is_active=True,
                venue__is_active=True,
            )
        except Space.DoesNotExist:
            from ..errors import unavailable

            raise unavailable("El espacio") from None
        _expire_overdue(authorization)
        candidate = Range(start, end, bounds="[)")
        rows = Reservation.objects.select_related("event_request").filter(
            organization_id=authorization.organization_id,
            space=space,
            status__in=[Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED],
            event_interval__overlap=candidate,
        )
        blocks = tuple(
            {
                **_reservation_summary(row),
                "event_request_id": row.event_request_id,
                "event_type": row.event_request.event_type,
            }
            for row in rows.order_by("event_interval", "id")
        )
        return {
            "space": {
                "id": space.pk,
                "name": space.name,
                "venue_id": space.venue_id,
                "venue_name": space.venue.name,
            },
            "from": start,
            "to": end,
            "available": not blocks,
            "blocks": blocks,
        }
