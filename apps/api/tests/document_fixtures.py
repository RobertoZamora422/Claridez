from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.services import (
    accept_quotation_version,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    replace_quotation_draft,
)
from claridez.identity.models import User
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.services import create_organization

PASSWORD = "documents-test-password-42!"


@dataclass(frozen=True, slots=True)
class DocumentCase:
    owner: User
    organization_id: UUID
    reservation: dict[str, Any]
    quotation: dict[str, Any]


def build_document_case(slug: str = "documents") -> DocumentCase:
    suffix = uuid4().hex
    owner = User.objects.create_user(
        email=f"{slug}-{suffix}@example.test",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    creation = create_organization(
        owner_user_id=owner.pk,
        name=f"Documentos {slug} {suffix}",
        slug=f"{slug}-{suffix}",
    )
    organization_id = creation.organization.pk
    event_type = next(iter(list_event_types(owner, organization_id)), None)
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name="Evento documental")
    venue = list_venues(owner, organization_id)[0]
    person = create_person(
        owner,
        organization_id,
        full_name="María Contraparte",
        phone=f"09{uuid4().int % 100000000:08d}",
        email="counterparty@example.test",
        origin="referral",
        origin_detail=None,
    )
    starts_at = timezone.now() + timedelta(days=45)
    request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type["id"],
        space_id=venue["spaces"][0]["id"],
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=5),
        estimated_guests=80,
        general_need="Evento con evidencia contractual",
        notes="Datos sintéticos",
        origin="referral",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=request["id"],
        valid_until=timezone.now() + timedelta(days=5),
    )
    draft = quotation["versions"][0]
    quotation = replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=draft["revision"],
        valid_until=timezone.now() + timedelta(days=5),
        notes="Condiciones comerciales congeladas",
        lines=[
            {
                "description": "Alquiler del espacio",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("900.00"),
                "discount_amount": Decimal("50.00"),
            },
            {
                "description": "Servicio por invitado",
                "unit_label": "persona",
                "quantity": Decimal("80.000"),
                "unit_price": Decimal("4.25"),
                "discount_amount": Decimal("0.00"),
            },
        ],
    )
    issue_quotation_version(owner, organization_id, quotation_id=quotation["id"], version=1)
    reservation = accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="email",
        note="Aceptación comercial sintética",
    )
    return DocumentCase(owner, organization_id, reservation, quotation)
