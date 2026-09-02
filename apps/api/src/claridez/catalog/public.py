"""Puerto público inmutable del catálogo para consumidores operativos."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .models import EventType


@dataclass(frozen=True, slots=True)
class OperationalEventTypeProjection:
    id: UUID
    name: str
    is_active: bool
    revision: int


@dataclass(frozen=True, slots=True)
class PublicEventTypeProjection:
    id: UUID
    label: str
    revision: int


def event_type_for_operations(
    organization_id: UUID, event_type_id: UUID
) -> OperationalEventTypeProjection | None:
    row = EventType.objects.filter(organization_id=organization_id, pk=event_type_id).first()
    if row is None:
        return None
    return OperationalEventTypeProjection(
        id=row.pk,
        name=row.name,
        is_active=row.is_active,
        revision=row.revision,
    )


def event_types_for_operations(organization_id: UUID) -> tuple[OperationalEventTypeProjection, ...]:
    return tuple(
        OperationalEventTypeProjection(
            id=row.pk,
            name=row.name,
            is_active=row.is_active,
            revision=row.revision,
        )
        for row in EventType.objects.filter(
            organization_id=organization_id, is_active=True
        ).order_by("name", "id")
    )


def public_event_type(
    organization_id: UUID, event_type_id: UUID
) -> PublicEventTypeProjection | None:
    row = EventType.objects.filter(
        organization_id=organization_id, pk=event_type_id, is_active=True
    ).first()
    if row is None:
        return None
    return PublicEventTypeProjection(id=row.pk, label=row.name, revision=row.revision)


__all__ = (
    "OperationalEventTypeProjection",
    "PublicEventTypeProjection",
    "event_type_for_operations",
    "event_types_for_operations",
    "public_event_type",
)
