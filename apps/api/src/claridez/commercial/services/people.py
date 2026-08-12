"""Adaptador comercial compatible hacia el puerto público de people."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope
from claridez.people import public as people_port
from claridez.scheduling.public import confirmed_event_request_ids

from ..errors import CommercialError
from ..models import EventRequest


def _people_call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except people_port.PeopleError as error:
        raise CommercialError(error.code, error.message, status=error.status) from error


def _commercial_type(authorization: TenantAuthorization, person_id: UUID) -> str:
    cluster = people_port.canonical_cluster_ids(authorization.organization_id, person_id)
    request_ids = tuple(
        EventRequest.objects.filter(
            organization_id=authorization.organization_id, person_id__in=cluster
        ).values_list("id", flat=True)
    )
    return "client" if confirmed_event_request_ids(authorization, request_ids) else "lead"


def _decorate(
    actor: User, organization_reference: UUID | str, data: dict[str, Any]
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        return {
            **data,
            "commercial_type": _commercial_type(authorization, UUID(str(data["canonical_id"]))),
        }


def list_people(
    actor: User, organization_reference: UUID | str, *, query: str = ""
) -> tuple[dict[str, Any], ...]:
    rows = _people_call(lambda: people_port.list_people(actor, organization_reference, query=query))
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        return tuple(
            {
                **row,
                "commercial_type": _commercial_type(authorization, UUID(str(row["canonical_id"]))),
            }
            for row in rows
        )


def create_person(
    actor: User,
    organization_reference: UUID | str,
    *,
    full_name: str,
    phone: str,
    email: str | None,
    origin: str,
    origin_detail: str | None,
) -> dict[str, Any]:
    return _decorate(
        actor,
        organization_reference,
        _people_call(
            lambda: people_port.create_person(
                actor,
                organization_reference,
                full_name=full_name,
                phone=phone,
                email=email,
                origin=origin,
                origin_detail=origin_detail,
            )
        ),
    )


def read_person(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> dict[str, Any]:
    return _decorate(
        actor,
        organization_reference,
        _people_call(
            lambda: people_port.read_person(actor, organization_reference, person_id=person_id)
        ),
    )


def update_person(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    revision: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    return _decorate(
        actor,
        organization_reference,
        _people_call(
            lambda: people_port.update_person(
                actor,
                organization_reference,
                person_id=person_id,
                revision=revision,
                changes=changes,
            )
        ),
    )


def list_person_revisions(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> tuple[dict[str, Any], ...]:
    return _people_call(
        lambda: people_port.list_person_revisions(
            actor, organization_reference, person_id=person_id
        )
    )
