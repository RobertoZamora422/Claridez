"""Proyección de acceso actual; nunca pretende ser un hecho métrico histórico."""

from dataclasses import dataclass
from uuid import UUID

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import EventRequest


@dataclass(frozen=True, slots=True)
class AnalyticsScheduleContext:
    request_ids: tuple[UUID, ...]
    space_ids: tuple[UUID, ...]


def schedule_context_for_analytics(authorization: TenantAuthorization) -> AnalyticsScheduleContext:
    """Agenda comercial contextual de sus solicitudes; acceso revalidado al consultar/exportar."""
    authorization.require(Capability.SALES_READ)
    rows = tuple(
        EventRequest.objects.filter(
            organization_id=authorization.organization_id,
            responsible_membership_id=authorization.membership_id,
        )
        .order_by("id")
        .values_list("id", "space_id")
    )
    return AnalyticsScheduleContext(
        tuple(row[0] for row in rows), tuple(sorted({row[1] for row in rows}))
    )
