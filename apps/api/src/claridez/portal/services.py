from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Max
from django.utils import timezone

from claridez.catalog.public import public_event_type
from claridez.commercial.public import (
    client_event_request,
    client_quotations,
    create_public_event_request,
)
from claridez.communications.public import (
    PreferenceAction,
    Purpose,
    append_preference,
    published_template_channel_if_compatible,
    published_template_for_purpose,
    request_intent,
)
from claridez.external_secrets import short_single_use_code
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.public import (
    authorize_external_entry,
    public_location,
    public_organization,
    public_responsible,
)
from claridez.organizations.tenant_scope import (
    ExternalTenantAuthorization,
    TenantAuthorization,
    authorized_tenant_scope,
    external_tenant_scope,
)
from claridez.people.public import (
    canonical_cluster_ids,
    canonical_person_id,
    capture_origin_is_valid,
    contact_for_external_control,
    record_external_consent,
    resolve_contact_for_portal,
    resolve_or_create_for_capture,
)
from claridez.receivables.public import client_receivables
from claridez.scheduling.public import client_schedule, public_interval_availability

from .errors import PortalError, conflict, forbidden, invalid, unavailable
from .models import (
    PortalAuditEvent,
    PortalChallenge,
    PortalGrant,
    PortalLocator,
    PortalPrincipal,
    PortalSession,
    PublicForm,
    PublicFormSubmission,
    PublicFormVersion,
)
from .security import digest, payload_hash, random_token

PORTAL_SCOPES = frozenset(
    {
        "event:read",
        "quotation:read",
        "schedule:read",
        "documents:read",
        "documents:download",
        "documents:accept",
        "receivables:read",
        "preferences:manage",
    }
)
PUBLIC_FORM_REQUIRED_FIELDS = frozenset(
    {
        "full_name",
        "phone",
        "event_type_id",
        "space_id",
        "starts_at_local",
        "duration_minutes",
        "estimated_guests",
        "general_need",
    }
)


def _require_scope_capabilities(authorization: TenantAuthorization, scopes: list[str]) -> None:
    requirements = {
        "schedule:read": Capability.AVAILABILITY_READ,
        "documents:read": Capability.CONTRACTUAL_RECORD_READ,
        "documents:download": Capability.DOCUMENT_ARTIFACT_DOWNLOAD,
        "documents:accept": Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
        "receivables:read": Capability.RECEIVABLES_READ_SUMMARY,
    }
    for scope in sorted(set(scopes)):
        required = requirements.get(scope)
        if required is not None:
            authorization.require(required)


def _validate_form_schema(field_schema: object, consent_presentation: object) -> None:
    if not isinstance(field_schema, dict) or not isinstance(consent_presentation, list):
        raise invalid("La configuración estructurada del formulario no es válida.")
    required_value = field_schema.get("required", [])
    required_fields = set(required_value if isinstance(required_value, list) else [])
    optional_value = field_schema.get("optional", [])
    optional_fields = set(optional_value if isinstance(optional_value, list) else [])
    if (
        required_fields != PUBLIC_FORM_REQUIRED_FIELDS
        or optional_fields != {"email", "notes"}
        or set(field_schema) - {"required", "optional", "labels"}
        or not isinstance(field_schema.get("labels", {}), dict)
    ):
        raise invalid("El esquema cerrado no contiene todos los campos obligatorios.")
    consent_keys: set[str] = set()
    for item in consent_presentation:
        if not isinstance(item, dict):
            raise invalid("La presentación de consentimiento no es verificable.")
        text = str(item.get("text", ""))
        purpose = str(item.get("purpose", ""))
        channel = str(item.get("channel", ""))
        consent_key = f"{purpose}:{channel}"
        if (
            not text
            or hashlib.sha256(text.encode()).hexdigest() != str(item.get("text_sha256", ""))
            or purpose not in Purpose.values
            or channel not in {"email", "whatsapp", "phone"}
            or not str(item.get("version", ""))
            or consent_key in consent_keys
        ):
            raise invalid("La presentación de consentimiento no es verificable.")
        consent_keys.add(consent_key)


def _observed_attribution(value: object) -> dict[str, str | int | bool]:
    if not isinstance(value, dict) or len(value) > 20:
        raise invalid("La atribución observada no es válida.")
    result: dict[str, str | int | bool] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or len(key) > 64 or not isinstance(raw_value, (str, int, bool)):
            raise invalid("La atribución observada no es válida.")
        if isinstance(raw_value, str):
            normalized_string = raw_value.strip()
            if len(normalized_string) > 240:
                raise invalid("La atribución observada no es válida.")
            normalized: str | int | bool = normalized_string
        else:
            normalized = raw_value
        result[key] = normalized
    return result


def _new_locator(
    organization_id: UUID,
    *,
    kind: str,
    target_reference: UUID,
    expires_at: datetime | None = None,
) -> str:
    token = random_token()
    PortalLocator.objects.create(
        token_hmac=digest(token, purpose="locator"),
        organization_id=organization_id,
        kind=kind,
        target_reference=target_reference,
        expires_at=expires_at,
    )
    return token


def resolve_locator(
    token: str, *, kind: str, purpose: str
) -> tuple[ExternalTenantAuthorization, UUID]:
    now = timezone.now()
    row = PortalLocator.objects.filter(
        token_hmac=digest(token, purpose="locator"),
        kind=kind,
        revoked_at__isnull=True,
    ).first()
    if row is None or (row.expires_at is not None and row.expires_at <= now):
        raise unavailable()
    authorization = authorize_external_entry(
        row.organization_id, purpose=purpose, locator_reference=row.pk
    )
    return authorization, row.target_reference


def _validated_form_configuration(
    organization_id: UUID,
    *,
    event_type_options: list[dict[str, object]],
    location_options: list[dict[str, object]],
    duration_options_minutes: list[int],
    timezone_name: str,
    responsible_membership_id: UUID,
    portal_scopes: list[str],
    origin: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[int], list[str]]:
    organization = public_organization(organization_id)
    if organization.timezone_name != timezone_name:
        raise invalid("La zona observada no coincide con la configuración de la organización.")
    if not capture_origin_is_valid(origin):
        raise invalid("El origen configurado no puede producir una solicitud válida.")
    responsible = public_responsible(organization_id, membership_id=responsible_membership_id)
    if responsible is None or not responsible.is_active or not responsible.can_manage_sales:
        raise invalid("El formulario no tiene un responsable comercial válido.")
    event_types: list[dict[str, object]] = []
    locations: list[dict[str, object]] = []
    try:
        for option in event_type_options:
            event_type_item = public_event_type(organization_id, UUID(str(option.get("id"))))
            if event_type_item is None or event_type_item.revision != int(
                str(option.get("revision", 0))
            ):
                raise invalid("Un tipo de evento no es publicable en su revisión indicada.")
            event_types.append(
                {
                    "id": str(event_type_item.id),
                    "revision": event_type_item.revision,
                    "label": event_type_item.label,
                }
            )
        for option in location_options:
            location_item = public_location(
                organization_id, space_id=UUID(str(option.get("space_id")))
            )
            if (
                location_item is None
                or not location_item.is_active
                or location_item.space_revision != int(str(option.get("space_revision", 0)))
                or location_item.venue_revision != int(str(option.get("venue_revision", 0)))
            ):
                raise invalid("Un espacio no es publicable en su revisión indicada.")
            locations.append(
                {
                    "venue_id": str(location_item.venue_id),
                    "venue_revision": location_item.venue_revision,
                    "venue_label": location_item.venue_name,
                    "space_id": str(location_item.space_id),
                    "space_revision": location_item.space_revision,
                    "space_label": location_item.space_name,
                }
            )
        durations = sorted(
            {int(str(value)) for value in duration_options_minutes if 15 <= int(str(value)) <= 1440}
        )
    except (TypeError, ValueError, AttributeError):
        raise invalid("La configuración publicada contiene referencias inválidas.") from None
    scopes = sorted(set(portal_scopes))
    if (
        not event_types
        or len({str(item["id"]) for item in event_types}) != len(event_types)
        or not locations
        or len({str(item["space_id"]) for item in locations}) != len(locations)
        or not durations
        or set(scopes) - PORTAL_SCOPES
    ):
        raise invalid("La configuración no puede producir una solicitud válida.")
    return event_types, locations, durations, scopes


def create_form(
    actor: User,
    organization_id: UUID,
    *,
    name: str,
    title: str,
    introduction: str,
    field_schema: dict[str, object],
    event_type_options: list[dict[str, object]],
    location_options: list[dict[str, object]],
    duration_options_minutes: list[int],
    timezone_name: str,
    responsible_membership_id: UUID,
    origin: str,
    origin_detail: str,
    attribution: dict[str, object],
    consent_presentation: list[dict[str, object]],
    portal_scopes: list[str],
    acknowledgement_template_version_id: UUID | None,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PUBLIC_FORM_MANAGE
    ) as authorization:
        authorization.require(Capability.SALES_MANAGE)
        _validate_form_schema(field_schema, consent_presentation)
        event_types, locations, durations, scopes = _validated_form_configuration(
            authorization.organization_id,
            event_type_options=event_type_options,
            location_options=location_options,
            duration_options_minutes=duration_options_minutes,
            timezone_name=timezone_name,
            responsible_membership_id=responsible_membership_id,
            portal_scopes=portal_scopes,
            origin=origin,
        )
        _require_scope_capabilities(authorization, scopes)
        configuration = {
            "fields": field_schema,
            "event_types": event_types,
            "locations": locations,
            "durations": durations,
            "timezone": timezone_name,
            "responsible": str(responsible_membership_id),
            "origin": origin,
            "origin_detail": origin_detail,
            "attribution": attribution,
            "consents": consent_presentation,
            "scopes": scopes,
            "acknowledgement_template_version_id": (
                str(acknowledgement_template_version_id)
                if acknowledgement_template_version_id
                else None
            ),
        }
        with transaction.atomic():
            form = PublicForm.objects.create(
                organization_id=authorization.organization_id,
                name=name.strip(),
                created_by_membership_id=authorization.membership_id,
            )
            version = PublicFormVersion.objects.create(
                organization_id=authorization.organization_id,
                form=form,
                version=1,
                title=title.strip(),
                introduction=introduction.strip(),
                field_schema=field_schema,
                event_type_options=event_types,
                location_options=locations,
                duration_options_minutes=durations,
                timezone_name=timezone_name,
                responsible_membership_id=responsible_membership_id,
                origin=origin,
                origin_detail=origin_detail,
                attribution=attribution,
                consent_presentation=consent_presentation,
                portal_scopes=scopes,
                acknowledgement_template_version_id=acknowledgement_template_version_id,
                configuration_sha256=payload_hash(configuration),
                created_by_membership_id=authorization.membership_id,
            )
            locator = _new_locator(
                authorization.organization_id,
                kind=PortalLocator.Kind.PUBLIC_FORM,
                target_reference=form.pk,
            )
        return {
            "id": form.pk,
            "version_id": version.pk,
            "locator": locator,
            "status": version.status,
        }


def publish_form(actor: User, organization_id: UUID, *, version_id: UUID) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PUBLIC_FORM_PUBLISH
    ) as authorization:
        authorization.require(Capability.SALES_MANAGE)
        try:
            row = PublicFormVersion.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=version_id,
                form__status=PublicForm.Status.ACTIVE,
            )
        except PublicFormVersion.DoesNotExist:
            raise unavailable() from None
        if row.status != PublicFormVersion.Status.DRAFT:
            raise conflict("immutable_form_version", "La versión ya no puede publicarse.")
        _validate_form_schema(dict(row.field_schema), list(row.consent_presentation))
        event_types, locations, durations, scopes = _validated_form_configuration(
            authorization.organization_id,
            event_type_options=list(row.event_type_options),
            location_options=list(row.location_options),
            duration_options_minutes=list(row.duration_options_minutes),
            timezone_name=row.timezone_name,
            responsible_membership_id=row.responsible_membership_id,
            portal_scopes=list(row.portal_scopes),
            origin=row.origin,
        )
        _require_scope_capabilities(authorization, list(row.portal_scopes))
        expected_configuration = {
            "fields": row.field_schema,
            "event_types": event_types,
            "locations": locations,
            "durations": durations,
            "timezone": row.timezone_name,
            "responsible": str(row.responsible_membership_id),
            "origin": row.origin,
            "origin_detail": row.origin_detail,
            "attribution": row.attribution,
            "consents": row.consent_presentation,
            "scopes": scopes,
            "acknowledgement_template_version_id": (
                str(row.acknowledgement_template_version_id)
                if row.acknowledgement_template_version_id
                else None
            ),
        }
        if payload_hash(expected_configuration) != row.configuration_sha256:
            raise conflict(
                "form_configuration_integrity_failed",
                "La configuración del formulario no coincide con su hash canónico.",
            )
        if row.acknowledgement_template_version_id and not (
            published_template_channel_if_compatible(
                authorization.organization_id,
                version_id=row.acknowledgement_template_version_id,
                purpose=Purpose.CAPTURE_ACKNOWLEDGEMENT,
                variable_names={"name", "event_request_id"},
            )
        ):
            raise invalid("El acuse configurado no usa una plantilla publicada compatible.")
        now = timezone.now()
        PublicFormVersion.objects.filter(
            organization_id=authorization.organization_id,
            form=row.form,
            status=PublicFormVersion.Status.PUBLISHED,
        ).update(status=PublicFormVersion.Status.RETIRED, retired_at=now)
        row.status = PublicFormVersion.Status.PUBLISHED
        row.published_at = now
        row.published_by_membership_id = authorization.membership_id
        row.save(update_fields=["status", "published_at", "published_by_membership_id"])
        return {"id": row.pk, "status": row.status, "published_at": row.published_at}


def rotate_form_locator(actor: User, organization_id: UUID, *, form_id: UUID) -> dict[str, str]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PUBLIC_FORM_PUBLISH
    ) as authorization:
        authorization.require(Capability.SALES_MANAGE)
        try:
            form = PublicForm.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=form_id,
                status=PublicForm.Status.ACTIVE,
                versions__status=PublicFormVersion.Status.PUBLISHED,
            )
        except PublicForm.DoesNotExist:
            raise unavailable() from None
        now = timezone.now()
        PortalLocator.objects.filter(
            organization_id=authorization.organization_id,
            kind=PortalLocator.Kind.PUBLIC_FORM,
            target_reference=form.pk,
            revoked_at__isnull=True,
        ).update(revoked_at=now)
        return {
            "locator": _new_locator(
                authorization.organization_id,
                kind=PortalLocator.Kind.PUBLIC_FORM,
                target_reference=form.pk,
            )
        }


def retire_form(actor: User, organization_id: UUID, *, form_id: UUID) -> None:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PUBLIC_FORM_PUBLISH
    ) as authorization:
        authorization.require(Capability.SALES_MANAGE)
        try:
            form = PublicForm.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=form_id,
                status=PublicForm.Status.ACTIVE,
            )
        except PublicForm.DoesNotExist:
            raise unavailable() from None
        now = timezone.now()
        form.status = PublicForm.Status.RETIRED
        form.save(update_fields=["status", "updated_at"])
        PublicFormVersion.objects.filter(
            organization_id=authorization.organization_id,
            form=form,
        ).exclude(status=PublicFormVersion.Status.RETIRED).update(
            status=PublicFormVersion.Status.RETIRED,
            retired_at=now,
        )
        PortalLocator.objects.filter(
            organization_id=authorization.organization_id,
            kind=PortalLocator.Kind.PUBLIC_FORM,
            target_reference=form.pk,
            revoked_at__isnull=True,
        ).update(revoked_at=now)


def create_form_version(
    actor: User,
    organization_id: UUID,
    *,
    form_id: UUID,
    title: str,
    introduction: str,
    field_schema: dict[str, object],
    event_type_options: list[dict[str, object]],
    location_options: list[dict[str, object]],
    duration_options_minutes: list[int],
    timezone_name: str,
    responsible_membership_id: UUID,
    origin: str,
    origin_detail: str,
    attribution: dict[str, object],
    consent_presentation: list[dict[str, object]],
    portal_scopes: list[str],
    acknowledgement_template_version_id: UUID | None,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PUBLIC_FORM_MANAGE
    ) as authorization:
        authorization.require(Capability.SALES_MANAGE)
        _validate_form_schema(field_schema, consent_presentation)
        try:
            form = PublicForm.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=form_id,
                status=PublicForm.Status.ACTIVE,
            )
        except PublicForm.DoesNotExist:
            raise unavailable() from None
        if form.versions.filter(status=PublicFormVersion.Status.DRAFT).exists():
            raise conflict("draft_exists", "El formulario ya tiene un borrador.")
        event_types, locations, durations, scopes = _validated_form_configuration(
            authorization.organization_id,
            event_type_options=event_type_options,
            location_options=location_options,
            duration_options_minutes=duration_options_minutes,
            timezone_name=timezone_name,
            responsible_membership_id=responsible_membership_id,
            portal_scopes=portal_scopes,
            origin=origin,
        )
        _require_scope_capabilities(authorization, scopes)
        next_version = (form.versions.aggregate(value=Max("version"))["value"] or 0) + 1
        configuration = {
            "fields": field_schema,
            "event_types": event_types,
            "locations": locations,
            "durations": durations,
            "timezone": timezone_name,
            "responsible": str(responsible_membership_id),
            "origin": origin,
            "origin_detail": origin_detail,
            "attribution": attribution,
            "consents": consent_presentation,
            "scopes": scopes,
            "acknowledgement_template_version_id": (
                str(acknowledgement_template_version_id)
                if acknowledgement_template_version_id
                else None
            ),
        }
        row = PublicFormVersion.objects.create(
            organization_id=authorization.organization_id,
            form=form,
            version=next_version,
            title=title.strip(),
            introduction=introduction.strip(),
            field_schema=field_schema,
            event_type_options=event_types,
            location_options=locations,
            duration_options_minutes=durations,
            timezone_name=timezone_name,
            responsible_membership_id=responsible_membership_id,
            origin=origin,
            origin_detail=origin_detail,
            attribution=attribution,
            consent_presentation=consent_presentation,
            portal_scopes=scopes,
            acknowledgement_template_version_id=acknowledgement_template_version_id,
            configuration_sha256=payload_hash(configuration),
            created_by_membership_id=authorization.membership_id,
        )
        return {"id": row.pk, "version": row.version, "status": row.status}


def _published_form(organization_id: UUID, form_id: UUID) -> PublicFormVersion:
    try:
        return PublicFormVersion.objects.select_related("form").get(
            organization_id=organization_id,
            form_id=form_id,
            form__status=PublicForm.Status.ACTIVE,
            status=PublicFormVersion.Status.PUBLISHED,
        )
    except PublicFormVersion.DoesNotExist:
        raise unavailable() from None


def read_public_form(locator: str) -> dict[str, object]:
    authorization, form_id = resolve_locator(
        locator, kind=PortalLocator.Kind.PUBLIC_FORM, purpose="public_form"
    )
    with external_tenant_scope(authorization):
        row = _published_form(authorization.organization_id, form_id)
        organization = public_organization(authorization.organization_id)
        return {
            "organization": organization.name,
            "title": row.title,
            "introduction": row.introduction,
            "fields": row.field_schema,
            "event_types": row.event_type_options,
            "locations": row.location_options,
            "durations_minutes": row.duration_options_minutes,
            "timezone": row.timezone_name,
            "consents": row.consent_presentation,
            "version": row.version,
        }


def public_availability(
    locator: str,
    *,
    event_type_id: UUID,
    space_id: UUID,
    starts_at_local: str,
    duration_minutes: int,
) -> dict[str, object]:
    authorization, form_id = resolve_locator(
        locator, kind=PortalLocator.Kind.PUBLIC_FORM, purpose="public_form"
    )
    with external_tenant_scope(authorization):
        row = _published_form(authorization.organization_id, form_id)
        starts_at, ends_at = _resolve_public_interval(
            row,
            starts_at_local=starts_at_local,
            duration_minutes=duration_minutes,
        )
        _selected_options(
            row,
            event_type_id=event_type_id,
            space_id=space_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        projection = public_interval_availability(
            authorization.organization_id,
            space_id=space_id,
            starts_at=starts_at,
            ends_at=ends_at,
            timezone_name=row.timezone_name,
        )
        return asdict(projection)


def _resolve_public_interval(
    row: PublicFormVersion, *, starts_at_local: str, duration_minutes: int
) -> tuple[datetime, datetime]:
    if duration_minutes not in row.duration_options_minutes:
        raise invalid("La duración no pertenece a la versión publicada.")
    try:
        naive = datetime.strptime(starts_at_local, "%Y-%m-%dT%H:%M")
        zone = ZoneInfo(row.timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        raise invalid("La fecha local o zona publicada no es válida.") from None
    candidates = tuple(naive.replace(tzinfo=zone, fold=fold) for fold in (0, 1))
    valid = tuple(
        candidate
        for candidate in candidates
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive
    )
    if not valid or valid[0].utcoffset() != valid[-1].utcoffset():
        raise invalid("La hora local es inexistente o ambigua en la zona publicada.")
    starts_at = valid[0]
    ends_at = (starts_at.astimezone(UTC) + timedelta(minutes=duration_minutes)).astimezone(zone)
    return starts_at, ends_at


def _selected_options(
    row: PublicFormVersion,
    *,
    event_type_id: UUID,
    space_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    event_type = next(
        (item for item in row.event_type_options if str(item.get("id")) == str(event_type_id)), None
    )
    location = next(
        (item for item in row.location_options if str(item.get("space_id")) == str(space_id)), None
    )
    minutes = int((ends_at - starts_at).total_seconds() // 60)
    if event_type is None or location is None or minutes not in row.duration_options_minutes:
        raise invalid("La selección no pertenece a la versión publicada.")
    if starts_at >= ends_at:
        raise invalid("El intervalo no es válido.")
    return event_type, location


def _principal_and_grant(
    organization_id: UUID,
    *,
    person_id: UUID,
    event_request_id: UUID,
    scopes: list[str],
    provenance: str = "public_capture",
    issued_by_membership_id: UUID | None = None,
) -> tuple[PortalPrincipal, PortalGrant, bool]:
    cluster = canonical_cluster_ids(organization_id, person_id)
    principals = list(
        PortalPrincipal.objects.select_for_update().filter(
            organization_id=organization_id,
            person_reference__in=cluster,
            state__in=[PortalPrincipal.State.ACTIVE, PortalPrincipal.State.COLLISION],
        )
    )
    if any(row.state == PortalPrincipal.State.COLLISION for row in principals):
        raise conflict(
            "principal_merge_collision",
            "La identidad externa requiere conciliación auditada antes de ampliar acceso.",
        )
    if len(principals) > 1:
        ids = [row.pk for row in principals]
        reconciled_at = timezone.now()
        PortalPrincipal.objects.filter(pk__in=ids).update(
            state=PortalPrincipal.State.COLLISION,
            revision=F("revision") + 1,
            reconciled_at=reconciled_at,
        )
        PortalSession.objects.filter(
            organization_id=organization_id, principal_id__in=ids, revoked_at__isnull=True
        ).update(revoked_at=reconciled_at, revocation_reason="person_merge_collision")
        PortalAuditEvent.objects.create(
            organization_id=organization_id,
            kind="principal_merge_collision",
            result="blocked",
            detail={"principal_count": len(ids)},
            occurred_at=reconciled_at,
        )
        raise conflict(
            "principal_merge_collision",
            "La identidad externa requiere conciliación auditada antes de ampliar acceso.",
        )
    if principals:
        principal = _reconcile_principal(principals[0])
        if principal is None:
            raise conflict(
                "principal_merge_collision",
                "La identidad externa requiere conciliación auditada antes de ampliar acceso.",
            )
    else:
        principal = PortalPrincipal.objects.create(
            organization_id=organization_id,
            person_reference=canonical_person_id(organization_id, person_id),
            canonical_set=[str(item) for item in cluster],
        )
    grant, created = PortalGrant.objects.get_or_create(
        organization_id=organization_id,
        principal=principal,
        event_request_reference=event_request_id,
        state=PortalGrant.State.ACTIVE,
        defaults={
            "person_reference": canonical_person_id(organization_id, person_id),
            "scopes": scopes,
            "provenance": provenance,
            "issued_by_membership_id": issued_by_membership_id,
        },
    )
    return principal, grant, created


def submit_public_form(
    locator: str,
    *,
    idempotency_key: str,
    data: dict[str, object],
) -> dict[str, object]:
    if not idempotency_key.strip():
        raise invalid("La clave de idempotencia es obligatoria.")
    authorization, form_id = resolve_locator(
        locator, kind=PortalLocator.Kind.PUBLIC_FORM, purpose="public_form"
    )
    with external_tenant_scope(authorization):
        row = _published_form(authorization.organization_id, form_id)
        event_type_id = UUID(str(data["event_type_id"]))
        space_id = UUID(str(data["space_id"]))
        starts_at, ends_at = _resolve_public_interval(
            row,
            starts_at_local=str(data["starts_at_local"]),
            duration_minutes=int(str(data["duration_minutes"])),
        )
        event_type, location = _selected_options(
            row,
            event_type_id=event_type_id,
            space_id=space_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        observed_attribution = _observed_attribution(data.get("attribution", {}))
        consent_answers = data.get("consents", {})
        if not isinstance(consent_answers, dict):
            raise invalid("La presentación de consentimiento no es válida.")
        expected_consent_keys = {
            f"{str(item.get('purpose', ''))}:{str(item.get('channel', ''))}"
            for item in row.consent_presentation
        }
        if set(consent_answers) - expected_consent_keys or any(
            not isinstance(value, bool) for value in consent_answers.values()
        ):
            raise invalid("La presentación de consentimiento no es válida.")
        payload_sha = payload_hash(data)
        key_hmac = digest(idempotency_key, purpose=f"submission:{row.pk}")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"portal-submission:{authorization.organization_id}:{row.pk}:{key_hmac}"],
            )
        existing = PublicFormSubmission.objects.filter(
            organization_id=authorization.organization_id,
            form_version=row,
            idempotency_key_hmac=key_hmac,
        ).first()
        if existing:
            if existing.payload_sha256 != payload_sha:
                raise conflict("idempotency_conflict", "La clave ya fue usada con otros datos.")
            if existing.state == PublicFormSubmission.State.COMPLETED:
                return {
                    "submission_id": existing.pk,
                    "event_request_id": existing.event_request_reference,
                    "availability": existing.availability_observed,
                }
            raise conflict("submission_in_progress", "La solicitud ya se está procesando.")
        evidence_sha = payload_hash(
            {
                "form_version": str(row.pk),
                "configuration": row.configuration_sha256,
                "payload": payload_sha,
                "consents": row.consent_presentation,
            }
        )
        with transaction.atomic():
            submission = PublicFormSubmission.objects.create(
                organization_id=authorization.organization_id,
                form_version=row,
                idempotency_key_hmac=key_hmac,
                payload_sha256=payload_sha,
                evidence_sha256=evidence_sha,
                attribution_sha256=payload_hash(
                    {"configured": row.attribution, "observed": observed_attribution}
                ),
            )
            person = resolve_or_create_for_capture(
                authorization.organization_id,
                full_name=str(data["full_name"]),
                phone=str(data["phone"]),
                email=str(data.get("email", "")),
                origin=row.origin,
                origin_detail=row.origin_detail,
                evidence_reference=f"portal-submission:{submission.pk}",
                evidence_sha256=evidence_sha,
            )
            consent_ids: list[str] = []
            for item in row.consent_presentation:
                purpose = str(item.get("purpose", ""))
                channel = str(item.get("channel", ""))
                required = bool(item.get("required", False))
                consent_key = f"{purpose}:{channel}"
                if consent_key not in consent_answers:
                    if required:
                        raise invalid("Falta una decisión de consentimiento requerida.")
                    continue
                granted = consent_answers[consent_key]
                if required and not granted:
                    raise invalid("Falta una decisión de consentimiento requerida.")
                event = record_external_consent(
                    authorization.organization_id,
                    person_id=person.id,
                    purpose=purpose,
                    channel=channel,
                    decision="granted" if granted else "revoked",
                    evidence_reference=f"portal-submission:{submission.pk}",
                    submission_reference=f"portal-submission:{submission.pk}",
                    evidence_sha256=evidence_sha,
                    observed_text_sha256=str(item.get("text_sha256", "")),
                    presentation_version=str(item.get("version", "")),
                    occurred_at=timezone.now(),
                )
                consent_ids.append(str(event.id))
            availability = public_interval_availability(
                authorization.organization_id,
                space_id=space_id,
                starts_at=starts_at,
                ends_at=ends_at,
                timezone_name=row.timezone_name,
            ).available
            event_request_id = create_public_event_request(
                authorization.organization_id,
                person_id=person.id,
                event_type_id=event_type_id,
                event_type_revision=int(str(event_type["revision"])),
                space_id=space_id,
                space_revision=int(str(location["space_revision"])),
                venue_revision=int(str(location["venue_revision"])),
                starts_at=starts_at,
                ends_at=ends_at,
                estimated_guests=int(str(data["estimated_guests"])),
                general_need=str(data["general_need"]),
                notes=str(data.get("notes", "")),
                origin=row.origin,
                origin_detail=row.origin_detail,
                responsible_membership_id=row.responsible_membership_id,
                timezone_name=row.timezone_name,
            )
            principal, grant, _ = _principal_and_grant(
                authorization.organization_id,
                person_id=person.id,
                event_request_id=event_request_id,
                scopes=list(row.portal_scopes),
            )
            if row.acknowledgement_template_version_id:
                acknowledgement_channel = published_template_channel_if_compatible(
                    authorization.organization_id,
                    version_id=row.acknowledgement_template_version_id,
                    purpose=Purpose.CAPTURE_ACKNOWLEDGEMENT,
                    variable_names={"name", "event_request_id"},
                )
                if acknowledgement_channel is None:
                    raise conflict(
                        "published_form_configuration_changed",
                        "La configuración publicada ya no está disponible.",
                    )
                request_intent(
                    authorization.organization_id,
                    purpose=Purpose.CAPTURE_ACKNOWLEDGEMENT,
                    channel=acknowledgement_channel,
                    person_id=person.id,
                    template_version_id=row.acknowledgement_template_version_id,
                    aggregate_type="event_request",
                    aggregate_id=event_request_id,
                    variables={"name": person.full_name, "event_request_id": str(event_request_id)},
                    idempotency_key=f"capture:{submission.pk}",
                )
            submission.state = PublicFormSubmission.State.COMPLETED
            submission.person_reference = person.id
            submission.event_request_reference = event_request_id
            submission.consent_event_references = consent_ids
            submission.availability_observed = availability
            submission.completed_at = timezone.now()
            submission.save()
            PortalAuditEvent.objects.create(
                organization_id=authorization.organization_id,
                kind="public_capture_completed",
                principal_reference=principal.pk,
                grant_reference=grant.pk,
                result="success",
                detail={"form_version": str(row.pk)},
                occurred_at=timezone.now(),
            )
        return {
            "submission_id": submission.pk,
            "event_request_id": event_request_id,
            "availability": availability,
        }


def _reconcile_principal(principal: PortalPrincipal) -> PortalPrincipal | None:
    cluster = canonical_cluster_ids(principal.organization_id, principal.person_reference)
    collisions = PortalPrincipal.objects.filter(
        organization_id=principal.organization_id,
        person_reference__in=cluster,
        state=PortalPrincipal.State.ACTIVE,
    ).exclude(pk=principal.pk)
    if collisions.exists():
        ids = [principal.pk, *collisions.values_list("pk", flat=True)]
        reconciled_at = timezone.now()
        PortalPrincipal.objects.filter(pk__in=ids).update(
            state=PortalPrincipal.State.COLLISION,
            revision=F("revision") + 1,
            reconciled_at=reconciled_at,
        )
        PortalSession.objects.filter(
            organization_id=principal.organization_id,
            principal_id__in=ids,
            revoked_at__isnull=True,
        ).update(revoked_at=reconciled_at, revocation_reason="person_merge_collision")
        PortalAuditEvent.objects.create(
            organization_id=principal.organization_id,
            kind="principal_merge_collision",
            principal_reference=principal.pk,
            result="blocked",
            detail={"principal_count": len(ids)},
            occurred_at=reconciled_at,
        )
        return None
    canonical = canonical_person_id(principal.organization_id, principal.person_reference)
    canonical_set = [str(item) for item in cluster]
    if principal.person_reference != canonical or principal.canonical_set != canonical_set:
        previous_reference = principal.person_reference
        principal.person_reference = canonical
        principal.canonical_set = canonical_set
        principal.revision += 1
        principal.reconciled_at = timezone.now()
        principal.save(
            update_fields=["person_reference", "canonical_set", "revision", "reconciled_at"]
        )
        PortalAuditEvent.objects.create(
            organization_id=principal.organization_id,
            kind="principal_canonical_reconciled",
            principal_reference=principal.pk,
            result="success",
            detail={
                "previous_reference_sha256": hashlib.sha256(
                    str(previous_reference).encode()
                ).hexdigest(),
                "canonical_set_size": len(canonical_set),
            },
            occurred_at=timezone.now(),
        )
    return principal


def start_challenge(
    locator: str,
    *,
    channel: str,
    contact_value: str,
    kind: str = PortalChallenge.Kind.AUTHENTICATION,
) -> tuple[str | None, UUID | None]:
    if kind not in {
        PortalChallenge.Kind.AUTHENTICATION,
        PortalChallenge.Kind.ENROLLMENT,
        PortalChallenge.Kind.RECOVERY,
    }:
        raise invalid("El tipo de challenge no es válido.")
    authorization, form_id = resolve_locator(
        locator, kind=PortalLocator.Kind.PUBLIC_FORM, purpose="portal_authentication"
    )
    challenge_locator: str | None = None
    intent_id: UUID | None = None
    with external_tenant_scope(authorization):
        _published_form(authorization.organization_id, form_id)
        contact = resolve_contact_for_portal(
            authorization.organization_id, channel=channel, value=contact_value
        )
        if contact is None:
            return None, None
        principal = (
            PortalPrincipal.objects.filter(
                organization_id=authorization.organization_id,
                person_reference__in=contact.canonical_cluster_ids,
                state=PortalPrincipal.State.ACTIVE,
                grants__state=PortalGrant.State.ACTIVE,
            )
            .distinct()
            .first()
        )
        if principal is None:
            return None, None
        principal = _reconcile_principal(principal)
        if principal is None:
            return None, None
        challenge = PortalChallenge.objects.create(
            organization_id=authorization.organization_id,
            principal=principal,
            kind=kind,
            channel=channel,
            contact_fingerprint=digest(contact.value, purpose="contact"),
            contact_revision=contact.person_revision,
            code_hmac="pending",
            expires_at=timezone.now() + timedelta(seconds=settings.PORTAL_CHALLENGE_TTL_SECONDS),
        )
        code = short_single_use_code(challenge.pk)
        challenge.code_hmac = digest(code, purpose="challenge-code")
        challenge.save(update_fields=["code_hmac"])
        locator_expires_at = min(
            challenge.expires_at,
            timezone.now() + timedelta(seconds=settings.PORTAL_EPHEMERAL_LOCATOR_TTL_SECONDS),
        )
        challenge_locator = _new_locator(
            authorization.organization_id,
            kind=PortalLocator.Kind.CHALLENGE,
            target_reference=challenge.pk,
            expires_at=locator_expires_at,
        )
        auth_template_id = published_template_for_purpose(
            authorization.organization_id,
            purpose=Purpose.PORTAL_AUTHENTICATION,
            channel=channel,
        )
        expose_test_code = bool(settings.PORTAL_EXPOSE_TEST_CHALLENGE_CODE) and (
            settings.COMMUNICATIONS_PROVIDER == "deterministic"
        )
        if (settings.COMMUNICATIONS_PROVIDER == "deterministic" and not expose_test_code) or (
            not auth_template_id and not expose_test_code
        ):
            now = timezone.now()
            challenge.revoked_at = now
            challenge.save(update_fields=["revoked_at"])
            PortalLocator.objects.filter(
                organization_id=authorization.organization_id,
                kind=PortalLocator.Kind.CHALLENGE,
                target_reference=challenge.pk,
                revoked_at__isnull=True,
            ).update(revoked_at=now)
            PortalAuditEvent.objects.create(
                organization_id=authorization.organization_id,
                kind="authentication_delivery_unavailable",
                principal_reference=principal.pk,
                result="configuration_missing",
                detail={"channel": channel},
                occurred_at=now,
            )
            return None, None
        if auth_template_id:
            intent = request_intent(
                authorization.organization_id,
                purpose=Purpose.PORTAL_AUTHENTICATION,
                channel=channel,
                person_id=principal.person_reference,
                template_version_id=auth_template_id,
                aggregate_type="portal_challenge",
                aggregate_id=challenge.pk,
                variables={
                    "challenge_reference": str(challenge.pk),
                },
                idempotency_key=f"portal-challenge:{challenge.pk}",
            )
            intent_id = intent.pk
        if expose_test_code:
            PortalAuditEvent.objects.create(
                organization_id=authorization.organization_id,
                kind="test_challenge_code_issued",
                principal_reference=principal.pk,
                result="test_only",
                detail={"challenge": str(challenge.pk)},
                occurred_at=timezone.now(),
            )
            return f"{challenge_locator}.{code}", intent_id
    return challenge_locator, intent_id


def verify_challenge(locator_and_code: str) -> tuple[str, PortalSession]:
    try:
        locator, code = locator_and_code.rsplit(".", 1)
    except ValueError:
        raise unavailable() from None
    authorization, challenge_id = resolve_locator(
        locator, kind=PortalLocator.Kind.CHALLENGE, purpose="portal_authentication"
    )
    failure: PortalError | None = None
    with external_tenant_scope(authorization):
        try:
            challenge = (
                PortalChallenge.objects.select_for_update()
                .select_related("principal")
                .get(organization_id=authorization.organization_id, pk=challenge_id)
            )
        except PortalChallenge.DoesNotExist:
            raise unavailable() from None
        now = timezone.now()
        if challenge.revoked_at or challenge.consumed_at or challenge.expires_at <= now:
            raise unavailable()
        challenge.attempt_count += 1
        if not hmac.compare_digest(challenge.code_hmac, digest(code, purpose="challenge-code")):
            update_fields = ["attempt_count"]
            if challenge.attempt_count >= challenge.max_attempts:
                challenge.revoked_at = now
                update_fields.append("revoked_at")
            challenge.save(update_fields=update_fields)
            if challenge.revoked_at is not None:
                PortalLocator.objects.filter(
                    organization_id=authorization.organization_id,
                    kind=PortalLocator.Kind.CHALLENGE,
                    target_reference=challenge.pk,
                    revoked_at__isnull=True,
                ).update(revoked_at=now)
            failure = unavailable()
        else:
            principal = _reconcile_principal(challenge.principal)
            if principal is None:
                challenge.revoked_at = now
                challenge.save(update_fields=["revoked_at"])
                PortalLocator.objects.filter(
                    organization_id=authorization.organization_id,
                    kind=PortalLocator.Kind.CHALLENGE,
                    target_reference=challenge.pk,
                    revoked_at__isnull=True,
                ).update(revoked_at=now)
                failure = conflict(
                    "principal_merge_collision", "La identidad requiere conciliación."
                )
            else:
                contact = contact_for_external_control(
                    authorization.organization_id,
                    person_id=principal.person_reference,
                    channel=challenge.channel,
                )
                if (
                    contact is None
                    or digest(contact.value, purpose="contact") != challenge.contact_fingerprint
                    or contact.person_revision != challenge.contact_revision
                ):
                    challenge.revoked_at = now
                    challenge.save(update_fields=["revoked_at"])
                    PortalLocator.objects.filter(
                        organization_id=authorization.organization_id,
                        kind=PortalLocator.Kind.CHALLENGE,
                        target_reference=challenge.pk,
                        revoked_at__isnull=True,
                    ).update(revoked_at=now)
                    failure = unavailable()
                else:
                    challenge.consumed_at = now
                    challenge.save(update_fields=["attempt_count", "consumed_at"])
                    token = random_token()
                    session = PortalSession.objects.create(
                        organization_id=authorization.organization_id,
                        principal=principal,
                        token_hmac=digest(token, purpose="session"),
                        contact_fingerprint=challenge.contact_fingerprint,
                        contact_revision=challenge.contact_revision,
                        idle_expires_at=now
                        + timedelta(seconds=settings.PORTAL_SESSION_IDLE_TTL_SECONDS),
                        absolute_expires_at=now
                        + timedelta(seconds=settings.PORTAL_SESSION_ABSOLUTE_TTL_SECONDS),
                        last_seen_at=now,
                    )
                    PortalLocator.objects.filter(
                        organization_id=authorization.organization_id,
                        kind=PortalLocator.Kind.CHALLENGE,
                        target_reference=challenge.pk,
                        revoked_at__isnull=True,
                    ).update(revoked_at=now)
                    PortalLocator.objects.create(
                        token_hmac=digest(token, purpose="locator"),
                        organization_id=authorization.organization_id,
                        kind=PortalLocator.Kind.SESSION,
                        target_reference=session.pk,
                    )
                    return token, session
    if failure is not None:
        raise failure
    raise unavailable()


def authenticate_session(token: str) -> tuple[ExternalTenantAuthorization, PortalSession]:
    authorization, session_id = resolve_locator(
        token, kind=PortalLocator.Kind.SESSION, purpose="portal_session"
    )
    failure: PortalError | None = None
    with external_tenant_scope(authorization):
        try:
            session = (
                PortalSession.objects.select_for_update()
                .select_related("principal")
                .get(organization_id=authorization.organization_id, pk=session_id)
            )
        except PortalSession.DoesNotExist:
            raise unavailable() from None
        now = timezone.now()
        if not hmac.compare_digest(session.token_hmac, digest(token, purpose="session")):
            raise unavailable()
        if session.revoked_at or session.principal.state != PortalPrincipal.State.ACTIVE:
            raise PortalError("session_revoked", "La sesión fue revocada.", status=401)
        if session.idle_expires_at <= now or session.absolute_expires_at <= now:
            if session.revoked_at is None:
                session.revoked_at = now
                session.revocation_reason = "expired_or_principal_inactive"
                session.save(update_fields=["revoked_at", "revocation_reason"])
            PortalLocator.objects.filter(
                organization_id=authorization.organization_id,
                kind=PortalLocator.Kind.SESSION,
                target_reference=session.pk,
                revoked_at__isnull=True,
            ).update(revoked_at=now)
            failure = PortalError("session_expired", "La sesión expiró.", status=401)
        else:
            principal = _reconcile_principal(session.principal)
            if principal is None:
                failure = conflict(
                    "principal_merge_collision", "La identidad requiere conciliación."
                )
            else:
                # El fingerprint almacenado se revalida en ambos canales de autenticación.
                matches = False
                for channel in ("email", "whatsapp"):
                    current = contact_for_external_control(
                        authorization.organization_id,
                        person_id=principal.person_reference,
                        channel=channel,
                    )
                    if (
                        current
                        and digest(current.value, purpose="contact") == session.contact_fingerprint
                    ):
                        matches = current.person_revision == session.contact_revision
                        break
                if not matches:
                    session.revoked_at = now
                    session.revocation_reason = "contact_changed"
                    session.save(update_fields=["revoked_at", "revocation_reason"])
                    PortalLocator.objects.filter(
                        organization_id=authorization.organization_id,
                        kind=PortalLocator.Kind.SESSION,
                        target_reference=session.pk,
                        revoked_at__isnull=True,
                    ).update(revoked_at=now)
                    failure = PortalError(
                        "contact_changed",
                        "El contacto cambió; vuelve a autenticarte.",
                        status=401,
                    )
                else:
                    session.last_seen_at = now
                    session.idle_expires_at = min(
                        session.absolute_expires_at,
                        now + timedelta(seconds=settings.PORTAL_SESSION_IDLE_TTL_SECONDS),
                    )
                    session.save(update_fields=["last_seen_at", "idle_expires_at"])
                    return authorization, session
    if failure is not None:
        raise failure
    raise unavailable()


def revoke_session(token: str) -> None:
    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        session.revoked_at = timezone.now()
        session.revocation_reason = "client_logout"
        session.save(update_fields=["revoked_at", "revocation_reason"])
        PortalLocator.objects.filter(
            organization_id=authorization.organization_id,
            kind=PortalLocator.Kind.SESSION,
            target_reference=session.pk,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())


def rotate_session(token: str) -> tuple[str, PortalSession]:
    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        now = timezone.now()
        new_token = random_token()
        PortalLocator.objects.filter(
            organization_id=authorization.organization_id,
            kind=PortalLocator.Kind.SESSION,
            target_reference=session.pk,
            revoked_at__isnull=True,
        ).update(revoked_at=now)
        session.token_hmac = digest(new_token, purpose="session")
        session.rotation += 1
        session.save(update_fields=["token_hmac", "rotation"])
        PortalLocator.objects.create(
            token_hmac=digest(new_token, purpose="locator"),
            organization_id=authorization.organization_id,
            kind=PortalLocator.Kind.SESSION,
            target_reference=session.pk,
        )
        return new_token, session


def _grant(session: PortalSession, grant_id: UUID, scope: str) -> PortalGrant:
    try:
        row = PortalGrant.objects.get(
            organization_id=session.organization_id,
            pk=grant_id,
            principal=session.principal,
            state=PortalGrant.State.ACTIVE,
        )
    except PortalGrant.DoesNotExist:
        raise forbidden() from None
    if scope not in row.scopes:
        raise forbidden()
    canonical = canonical_cluster_ids(session.organization_id, row.person_reference)
    event = client_event_request(session.organization_id, row.event_request_reference)
    if session.principal.person_reference not in canonical or event.person_id not in canonical:
        raise forbidden()
    return row


def portal_events(token: str) -> tuple[dict[str, object], ...]:
    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        grants = PortalGrant.objects.filter(
            organization_id=authorization.organization_id,
            principal=session.principal,
            state=PortalGrant.State.ACTIVE,
        ).order_by("created_at", "id")
        return tuple(
            {
                "grant_id": grant.pk,
                "scopes": grant.scopes,
                "event": asdict(
                    client_event_request(
                        authorization.organization_id, grant.event_request_reference
                    )
                ),
            }
            for grant in grants
            if "event:read" in grant.scopes
            and "event:read" in _grant(session, grant.pk, "event:read").scopes
        )


def portal_event(token: str, *, grant_id: UUID) -> dict[str, object]:
    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        grant = _grant(session, grant_id, "event:read")
        event = client_event_request(authorization.organization_id, grant.event_request_reference)
        result: dict[str, object] = {"event": asdict(event), "grant_id": grant.pk}
        if "quotation:read" in grant.scopes:
            result["quotations"] = [
                asdict(item)
                for item in client_quotations(
                    authorization.organization_id, grant.event_request_reference
                )
            ]
        if "schedule:read" in grant.scopes:
            schedule = client_schedule(authorization.organization_id, grant.event_request_reference)
            result["schedule"] = asdict(schedule) if schedule else None
            if schedule and grant.root_reservation_reference != schedule.root_reservation_id:
                grant.root_reservation_reference = schedule.root_reservation_id
                grant.revision += 1
                grant.save(update_fields=["root_reservation_reference", "revision"])
        if "receivables:read" in grant.scopes:
            receivables = client_receivables(
                authorization.organization_id, grant.event_request_reference
            )
            result["receivables"] = asdict(receivables) if receivables else None
        return result


def update_client_preference(
    token: str,
    *,
    grant_id: UUID,
    channel: str,
    purpose: str,
    allow: bool,
) -> None:
    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        grant = _grant(session, grant_id, "preferences:manage")
        append_preference(
            authorization.organization_id,
            person_id=grant.person_reference,
            channel=channel,
            purpose=purpose,
            action=(
                PreferenceAction.CLIENT_ALLOW if allow else PreferenceAction.CLIENT_UNSUBSCRIBE
            ),
            portal_principal_id=session.principal_id,
            evidence_sha256=payload_hash(
                {
                    "session": str(session.pk),
                    "grant": str(grant.pk),
                    "channel": channel,
                    "purpose": purpose,
                    "allow": allow,
                }
            ),
            reason="portal_client_action",
        )


def portal_documents_for_grant(token: str, *, grant_id: UUID) -> tuple[dict[str, object], ...]:
    from claridez.documents.public import PortalDocumentAuthorization, portal_documents

    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        grant = _grant(session, grant_id, "documents:read")
        document_authorization = PortalDocumentAuthorization(
            organization_id=authorization.organization_id,
            event_request_id=grant.event_request_reference,
            principal_reference=session.principal_id,
            grant_reference=grant.pk,
            action="read",
        )
        return tuple(asdict(item) for item in portal_documents(document_authorization))


def download_document_for_grant(
    token: str,
    *,
    grant_id: UUID,
    issued_version_id: UUID,
    artifact_id: UUID,
    expected_sha256: str,
) -> tuple[bytes, str, str]:
    from claridez.documents.public import (
        PortalDocumentAuthorization,
        download_portal_document,
    )

    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        grant = _grant(session, grant_id, "documents:download")
        return download_portal_document(
            PortalDocumentAuthorization(
                organization_id=authorization.organization_id,
                event_request_id=grant.event_request_reference,
                principal_reference=session.principal_id,
                grant_reference=grant.pk,
                action="download",
            ),
            issued_version_id=issued_version_id,
            artifact_id=artifact_id,
            expected_sha256=expected_sha256,
        )


def accept_document_for_grant(
    token: str,
    *,
    grant_id: UUID,
    issued_version_id: UUID,
    artifact_id: UUID,
    expected_sha256: str,
    manifestation_text: str,
    manifestation_version: str,
    idempotency_key: UUID,
    request_id: str,
    correlation_id: str,
    ip_address: str | None,
    user_agent: str | None,
) -> UUID:
    from claridez.documents.public import PortalDocumentAuthorization, accept_portal_document

    authorization, session = authenticate_session(token)
    with external_tenant_scope(authorization):
        grant = _grant(session, grant_id, "documents:accept")
        organization = public_organization(authorization.organization_id)
        evidence = accept_portal_document(
            PortalDocumentAuthorization(
                organization_id=authorization.organization_id,
                event_request_id=grant.event_request_reference,
                principal_reference=session.principal_id,
                grant_reference=grant.pk,
                action="accept",
            ),
            issued_version_id=issued_version_id,
            artifact_id=artifact_id,
            expected_sha256=expected_sha256,
            manifestation_text=manifestation_text,
            manifestation_version=manifestation_version,
            idempotency_key=idempotency_key,
            timezone_name=organization.timezone_name,
            request_id=request_id,
            correlation_id=correlation_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return evidence.pk


def list_forms(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PUBLIC_FORM_READ
    ) as authorization:
        rows = PublicForm.objects.filter(
            organization_id=authorization.organization_id
        ).prefetch_related("versions")
        return tuple(
            {
                "id": row.pk,
                "name": row.name,
                "status": row.status,
                "versions": [
                    {
                        "id": version.pk,
                        "version": version.version,
                        "status": version.status,
                        "title": version.title,
                        "introduction": version.introduction,
                        "field_schema": version.field_schema,
                        "event_type_options": version.event_type_options,
                        "location_options": version.location_options,
                        "duration_options_minutes": version.duration_options_minutes,
                        "timezone_name": version.timezone_name,
                        "responsible_membership_id": version.responsible_membership_id,
                        "origin": version.origin,
                        "origin_detail": version.origin_detail,
                        "attribution": version.attribution,
                        "consent_presentation": version.consent_presentation,
                        "portal_scopes": version.portal_scopes,
                        "acknowledgement_template_version_id": (
                            version.acknowledgement_template_version_id
                        ),
                        "configuration_sha256": version.configuration_sha256,
                    }
                    for version in row.versions.order_by("version", "id")
                ],
            }
            for row in rows.order_by("name", "id")
        )


def list_grants(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PORTAL_GRANT_READ
    ) as authorization:
        rows = PortalGrant.objects.filter(organization_id=authorization.organization_id)
        return tuple(
            {
                "id": row.pk,
                "principal_id": row.principal_id,
                "person_reference": row.person_reference,
                "event_request_reference": row.event_request_reference,
                "root_reservation_reference": row.root_reservation_reference,
                "scopes": row.scopes,
                "state": row.state,
                "revision": row.revision,
            }
            for row in rows.order_by("created_at", "id")
        )


def issue_grant(
    actor: User,
    organization_id: UUID,
    *,
    event_request_id: UUID,
    scopes: list[str],
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PORTAL_GRANT_ISSUE
    ) as authorization:
        authorization.require(Capability.SALES_READ)
        if not scopes or set(scopes) - PORTAL_SCOPES:
            raise invalid("Los scopes del grant no son válidos.")
        _require_scope_capabilities(authorization, scopes)
        request_projection = client_event_request(authorization.organization_id, event_request_id)
        normalized_scopes = sorted(set(scopes))
        principal, grant, created = _principal_and_grant(
            authorization.organization_id,
            person_id=request_projection.person_id,
            event_request_id=event_request_id,
            scopes=normalized_scopes,
            provenance="internal_issue",
            issued_by_membership_id=authorization.membership_id,
        )
        if not created and sorted(set(grant.scopes)) != normalized_scopes:
            raise conflict(
                "grant_scope_conflict",
                "El grant activo ya existe con otros scopes; no se ampliará automáticamente.",
            )
        return {"id": grant.pk, "principal_id": principal.pk, "state": grant.state}


def revoke_grant(actor: User, organization_id: UUID, *, grant_id: UUID, revision: int) -> None:
    with authorized_tenant_scope(
        actor, organization_id, Capability.PORTAL_GRANT_REVOKE
    ) as authorization:
        try:
            row = PortalGrant.objects.select_for_update().get(
                organization_id=authorization.organization_id, pk=grant_id
            )
        except PortalGrant.DoesNotExist:
            raise unavailable() from None
        if row.revision != revision or row.state != PortalGrant.State.ACTIVE:
            raise conflict("stale_grant", "El grant cambió; vuelve a cargarlo.")
        row.state = PortalGrant.State.REVOKED
        row.revision += 1
        row.revoked_at = timezone.now()
        row.revoked_by_membership_id = authorization.membership_id
        row.save(update_fields=["state", "revision", "revoked_at", "revoked_by_membership_id"])


def create_communications_webhook_locator(
    organization_id: UUID, *, sender_identity_id: UUID
) -> str:
    return _new_locator(
        organization_id,
        kind=PortalLocator.Kind.COMMUNICATIONS_WEBHOOK,
        target_reference=sender_identity_id,
    )


def create_webhook_locator_internal(
    actor: User, organization_id: UUID, *, sender_identity_id: UUID
) -> dict[str, str]:
    from claridez.communications.public import sender_identity_for_webhook

    with authorized_tenant_scope(
        actor, organization_id, Capability.BUSINESS_CONFIGURATION_MANAGE
    ) as authorization:
        if sender_identity_for_webhook(authorization.organization_id, sender_identity_id) is None:
            raise unavailable()
        token = create_communications_webhook_locator(
            authorization.organization_id, sender_identity_id=sender_identity_id
        )
        return {"locator": token}


def resolve_communications_webhook_locator(
    token: str,
) -> tuple[ExternalTenantAuthorization, UUID]:
    return resolve_locator(
        token,
        kind=PortalLocator.Kind.COMMUNICATIONS_WEBHOOK,
        purpose="communications_webhook",
    )
