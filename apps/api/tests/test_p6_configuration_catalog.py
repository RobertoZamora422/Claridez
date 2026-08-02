from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction
from django.test import Client
from django.utils import timezone

from claridez.catalog.errors import CatalogError
from claridez.catalog.services import (
    create_catalog_item,
    create_catalog_price,
    create_event_type,
    list_catalog_items,
    update_catalog_item,
)
from claridez.commercial.errors import CommercialError
from claridez.commercial.models import QuotationLine
from claridez.commercial.services import (
    accept_quotation_version,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    replace_quotation_draft,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import (
    configuration_capabilities,
    create_space,
    create_venue,
    list_venues,
    read_business_configuration,
    update_business_configuration,
)
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership, create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope

PASSWORD = "p6-configuration-catalog-tests-42!"


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _organization(prefix: str) -> tuple[User, Any]:
    owner = _user(f"{prefix}@example.com")
    return owner, create_organization(owner_user_id=owner.pk, name=f"Organización {prefix}")


def _actor(owner: User, organization_id: UUID, role: Membership.Role) -> User:
    if role == Membership.Role.OWNER:
        return owner
    actor = _user(f"p6-{role}-{organization_id}@example.com")
    add_membership(organization_id=organization_id, user_id=actor.pk, role=role)
    return actor


def _csrf_login(client: Client, actor: User) -> str:
    csrf = str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    response = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": actor.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


@pytest.mark.django_db
def test_p6_capabilities_separate_functional_admin_from_sensitive_memberships() -> None:
    owner, creation = _organization("capabilities")
    organization_id = creation.organization.pk
    administrator = _actor(owner, organization_id, Membership.Role.ADMINISTRATOR)
    commercial = _actor(owner, organization_id, Membership.Role.COMMERCIAL)
    operations = _actor(owner, organization_id, Membership.Role.OPERATIONS)
    finance = _actor(owner, organization_id, Membership.Role.FINANCE)

    full_management = {
        Capability.BUSINESS_CONFIGURATION_MANAGE.value,
        Capability.VENUE_MANAGE.value,
        Capability.CATALOG_MANAGE.value,
        Capability.CATALOG_PRICE_MANAGE.value,
    }
    assert full_management <= set(configuration_capabilities(owner, organization_id))
    assert full_management <= set(configuration_capabilities(administrator, organization_id))
    assert set(configuration_capabilities(commercial, organization_id)) == {
        Capability.BUSINESS_CONFIGURATION_READ.value,
        Capability.VENUE_READ.value,
        Capability.CATALOG_READ.value,
        Capability.CATALOG_PRICE_READ.value,
    }
    assert Capability.CATALOG_PRICE_READ.value not in configuration_capabilities(
        operations, organization_id
    )
    assert Capability.CATALOG_PRICE_READ.value in configuration_capabilities(
        finance, organization_id
    )

    with pytest.raises(AuthorizationDenied):
        update_business_configuration(
            commercial,
            organization_id,
            name="Cambio no autorizado",
            currency="USD",
            timezone="America/Guayaquil",
        )

    client = Client(enforce_csrf_checks=True)
    token = _csrf_login(client, administrator)
    response = client.patch(
        f"/api/v1/organizations/{organization_id}/configuration/",
        data=json.dumps(
            {
                "name": "Centro de eventos renovado",
                "currency": "USD",
                "timezone": "America/Guayaquil",
            }
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    assert read_business_configuration(owner, organization_id)["name"] == (
        "Centro de eventos renovado"
    )
    membership_mutation = client.post(
        f"/api/v1/organizations/{organization_id}/memberships/",
        data=json.dumps({"role": "owner"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert membership_mutation.status_code == 405


@pytest.mark.django_db
def test_configuration_manages_primary_venue_and_space_without_cross_tenant_access() -> None:
    owner, creation = _organization("venues")
    other_owner, other = _organization("other-venues")
    organization_id = creation.organization.pk

    initial = list_venues(owner, organization_id)
    assert len(initial) == 1
    assert initial[0]["is_primary"] is True
    assert initial[0]["spaces"][0]["is_primary"] is True

    venue = create_venue(
        owner,
        organization_id,
        name="Sede Norte",
        location_reference="Quito, sector norte",
        is_primary=True,
    )
    space = create_space(
        owner,
        organization_id,
        venue_id=venue["id"],
        name="Salón Jardín",
        is_primary=True,
    )
    current = list_venues(owner, organization_id)
    assert sum(row["is_primary"] for row in current) == 1
    assert sum(item["is_primary"] for row in current for item in row["spaces"]) == 1
    assert space["is_primary"] is True

    with pytest.raises(TenantAccessDenied):
        list_venues(other_owner, organization_id)
    assert len(list_venues(other_owner, other.organization.pk)) == 1


@pytest.mark.django_db
def test_catalog_versions_packages_prices_and_quotation_snapshots() -> None:
    owner, creation = _organization("catalog")
    organization_id = creation.organization.pk
    commercial = _actor(owner, organization_id, Membership.Role.COMMERCIAL)
    event_type = create_event_type(owner, organization_id, name="Boda")
    service = create_catalog_item(
        owner,
        organization_id,
        kind="service",
        name="Coordinación",
        description="Coordinación integral",
        unit_label="evento",
        components=[],
    )
    product = create_catalog_item(
        owner,
        organization_id,
        kind="product",
        name="Silla",
        description="Silla vestida",
        unit_label="unidad",
        components=[],
    )
    package = create_catalog_item(
        owner,
        organization_id,
        kind="package",
        name="Paquete esencial",
        description="Composición explícita",
        unit_label="evento",
        components=[
            {"item_id": service["id"], "quantity": Decimal("1.000")},
            {"item_id": product["id"], "quantity": Decimal("40.000")},
        ],
    )
    now = timezone.now()
    first_price = create_catalog_price(
        owner,
        organization_id,
        item_id=package["id"],
        amount=Decimal("800.00"),
        valid_from=now - timedelta(days=1),
        valid_until=None,
    )
    assert first_price["revision"] == 1
    visible = next(
        row for row in list_catalog_items(commercial, organization_id) if row["id"] == package["id"]
    )
    assert visible["current_price"]["amount"] == Decimal("800.00")
    assert [component["name"] for component in visible["components"]] == [
        "Coordinación",
        "Silla",
    ]
    with pytest.raises(AuthorizationDenied):
        create_catalog_item(
            commercial,
            organization_id,
            kind="service",
            name="No autorizado",
            description="",
            unit_label="evento",
            components=[],
        )

    person = create_person(
        commercial,
        organization_id,
        full_name="Cliente Catálogo",
        phone="0991234567",
        email="catalog-client@example.com",
        origin="website",
        origin_detail=None,
    )
    space_id = list_venues(owner, organization_id)[0]["spaces"][0]["id"]
    starts_at = now + timedelta(days=20)
    event_request = create_event_request(
        commercial,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type["id"],
        space_id=space_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=5),
        estimated_guests=40,
        general_need="Paquete completo",
        notes="",
        origin="website",
        origin_detail=None,
    )
    quotation = create_quotation(
        commercial,
        organization_id,
        request_id=event_request["id"],
        valid_until=now + timedelta(days=3),
    )
    quotation = replace_quotation_draft(
        commercial,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=1,
        valid_until=now + timedelta(days=3),
        notes="Catálogo y ajuste",
        lines=[
            {
                "catalog_item_id": package["id"],
                "quantity": Decimal("1.000"),
                "discount_amount": Decimal("50.00"),
                "description": "Intento de alterar snapshot",
                "unit_price": Decimal("1.00"),
            },
            {
                "description": "Ajuste ad hoc",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("25.00"),
            },
        ],
    )
    catalog_line_id = quotation["versions"][0]["lines"][0]["id"]
    with (
        authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE),
        pytest.raises(DatabaseError),
        transaction.atomic(),
    ):
        QuotationLine.objects.filter(pk=catalog_line_id).update(
            description="Snapshot alterado fuera del servicio"
        )
    issue_quotation_version(commercial, organization_id, quotation_id=quotation["id"], version=1)
    catalog_line, ad_hoc_line = quotation["versions"][0]["lines"]
    assert catalog_line["source"] == "catalog"
    assert catalog_line["description"] == "Paquete esencial"
    assert catalog_line["unit_price"] == Decimal("800.00")
    assert len(catalog_line["package_components"]) == 2
    assert ad_hoc_line["source"] == "ad_hoc"

    updated = update_catalog_item(
        owner,
        organization_id,
        item_id=package["id"],
        revision=package["revision"],
        name="Paquete esencial renovado",
        description="Nueva composición",
        unit_label="evento",
        is_active=True,
        components=[{"item_id": service["id"], "quantity": Decimal("2.000")}],
    )
    assert updated["revision"] == 2
    second_price = create_catalog_price(
        owner,
        organization_id,
        item_id=package["id"],
        amount=Decimal("900.00"),
        valid_from=timezone.now(),
        valid_until=None,
    )
    assert second_price["revision"] == 2
    assert catalog_line["description"] == "Paquete esencial"
    assert catalog_line["unit_price"] == Decimal("800.00")


def _accepted_for_space(
    owner: User,
    organization_id: UUID,
    *,
    event_type_id: UUID,
    space_id: UUID,
    phone: str,
    starts_at: Any,
) -> dict[str, Any]:
    person = create_person(
        owner,
        organization_id,
        full_name=f"Contacto {phone}",
        phone=phone,
        email=None,
        origin="phone_call",
        origin_detail=None,
    )
    event_request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type_id,
        space_id=space_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=4),
        estimated_guests=30,
        general_need="Evento simultáneo",
        notes="",
        origin="phone_call",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=event_request["id"],
        valid_until=timezone.now() + timedelta(days=3),
    )
    replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=1,
        valid_until=timezone.now() + timedelta(days=3),
        notes="",
        lines=[
            {
                "description": "Servicio ad hoc",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("100.00"),
            }
        ],
    )
    issue_quotation_version(owner, organization_id, quotation_id=quotation["id"], version=1)
    return accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="phone_call",
        note="Aceptada",
    )


@pytest.mark.django_db
def test_same_interval_is_allowed_across_spaces_and_rejected_within_one_space() -> None:
    owner, creation = _organization("multi-space")
    organization_id = creation.organization.pk
    event_type = create_event_type(owner, organization_id, name="Evento social")
    venue = list_venues(owner, organization_id)[0]
    first_space = venue["spaces"][0]
    second_space = create_space(
        owner,
        organization_id,
        venue_id=venue["id"],
        name="Salón paralelo",
    )
    starts_at = timezone.now() + timedelta(days=15)

    first = _accepted_for_space(
        owner,
        organization_id,
        event_type_id=event_type["id"],
        space_id=first_space["id"],
        phone="0991111111",
        starts_at=starts_at,
    )
    second = _accepted_for_space(
        owner,
        organization_id,
        event_type_id=event_type["id"],
        space_id=second_space["id"],
        phone="0992222222",
        starts_at=starts_at,
    )
    assert first["space_id"] == first_space["id"]
    assert second["space_id"] == second_space["id"]
    with pytest.raises(CommercialError) as collision:
        _accepted_for_space(
            owner,
            organization_id,
            event_type_id=event_type["id"],
            space_id=first_space["id"],
            phone="0993333333",
            starts_at=starts_at,
        )
    assert collision.value.code == "schedule_conflict"


@pytest.mark.django_db
def test_p6_http_mutations_require_csrf_and_catalog_manage_capability() -> None:
    owner, creation = _organization("http-security")
    organization_id = creation.organization.pk
    client = Client(enforce_csrf_checks=True)
    _csrf_login(client, owner)
    url = f"/api/v1/organizations/{organization_id}/event-types/"
    denied_csrf = client.post(
        url,
        data=json.dumps({"name": "Boda"}),
        content_type="application/json",
    )
    assert denied_csrf.status_code == 403

    token = str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    created = client.post(
        url,
        data=json.dumps({"name": "Boda"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert created.status_code == 201

    commercial = _actor(owner, organization_id, Membership.Role.COMMERCIAL)
    commercial_client = Client(enforce_csrf_checks=True)
    commercial_token = _csrf_login(commercial_client, commercial)
    forbidden = commercial_client.post(
        url,
        data=json.dumps({"name": "Graduación"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=commercial_token,
    )
    assert forbidden.status_code == 403

    with pytest.raises(CatalogError):
        create_catalog_price(
            owner,
            organization_id,
            item_id=UUID("00000000-0000-0000-0000-000000000001"),
            amount=Decimal("10.00"),
            valid_from=timezone.now(),
            valid_until=None,
        )
