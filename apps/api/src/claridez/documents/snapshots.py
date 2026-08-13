from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from claridez.commercial.public import accepted_quotation_for_documents
from claridez.organizations.public import contractual_organization
from claridez.organizations.tenant_scope import TenantAuthorization
from claridez.people.public import get_person
from claridez.scheduling.public import contractual_schedule

SCHEMA_VERSION = "contractual-snapshot-v1"


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def build_contractual_snapshot(
    authorization: TenantAuthorization, *, root_reservation_id: Any
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    schedule = contractual_schedule(authorization, root_reservation_id)
    quotation = accepted_quotation_for_documents(authorization, schedule.quotation_version_id)
    person = get_person(authorization.organization_id, quotation.person_id)
    organization = contractual_organization(authorization.organization_id)
    snapshot = _canonical(
        {
            "schema_version": SCHEMA_VERSION,
            "sources": {
                "organization": str(organization.id),
                "person": str(person.id),
                "quotation_version": str(quotation.id),
                "root_reservation": str(schedule.root_reservation_id),
                "current_reservation": str(schedule.current_reservation_id),
            },
            "organization": asdict(organization),
            "counterparty": {
                "id": person.id,
                "full_name": person.full_name,
                "phone": person.phone_e164,
                "email": person.email,
                "revision": person.revision,
            },
            "quotation": asdict(quotation),
            "reservation": asdict(schedule),
        }
    )
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    sha256 = hashlib.sha256(encoded).hexdigest()
    lines = quotation.lines
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(line.description)}</td>"
        f"<td>{html.escape(format(line.quantity, 'f'))}</td>"
        f"<td>{html.escape(format(line.unit_price, 'f'))}</td>"
        f"<td>{html.escape(format(line.line_total, 'f'))}</td>"
        "</tr>"
        for line in lines
    )
    values: dict[str, Any] = {
        "organization.name": organization.name,
        "organization.currency": organization.currency,
        "organization.timezone": organization.timezone_name,
        "counterparty.full_name": quotation.person_name,
        "counterparty.phone": quotation.person_phone,
        "counterparty.email": quotation.person_email,
        "quotation.number": quotation.visible_number,
        "quotation.version": quotation.version,
        "quotation.currency": quotation.currency,
        "quotation.subtotal": format(quotation.subtotal, "f"),
        "quotation.discount_total": format(quotation.discount_total, "f"),
        "quotation.total": format(quotation.total, "f"),
        "quotation.notes": quotation.quotation_notes,
        "quotation.accepted_at": quotation.accepted_at.isoformat(),
        "quotation.lines_table": (
            "<table><thead><tr><th>Servicio</th><th>Cantidad</th><th>Precio unitario"
            f"</th><th>Total</th></tr></thead><tbody>{rows}</tbody></table>"
        ),
        "reservation.root_id": str(schedule.root_reservation_id),
        "reservation.current_id": str(schedule.current_reservation_id),
        "reservation.venue_name": quotation.venue_name,
        "reservation.space_name": quotation.space_name,
        "reservation.starts_at": schedule.starts_at.isoformat(),
        "reservation.ends_at": schedule.ends_at.isoformat(),
        "reservation.timezone": schedule.timezone_name,
        "reservation.status": schedule.status,
    }
    provenance = {
        "schema": SCHEMA_VERSION,
        "commercial": "commercial.AcceptedQuotationProjection:v1",
        "scheduling": "scheduling.ContractualScheduleProjection:v1",
        "people": "people.PersonProjection:v1",
        "organizations": "organizations.OrganizationContractualProjection:v1",
    }
    return snapshot, sha256, values, provenance
