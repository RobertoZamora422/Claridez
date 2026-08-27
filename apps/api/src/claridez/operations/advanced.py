from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from psycopg.types.range import Range

import claridez.catalog.public as catalog_port
import claridez.commercial.public as commercial_port
import claridez.documents.public as documents_port
import claridez.organizations.public as organizations_port
import claridez.resources.public as resources_port
import claridez.scheduling.public as scheduling_port
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .advanced_models import (
    OperationalChangeDecision,
    OperationalChangeProposal,
    OperationalEvidence,
    OperationalIncident,
    OperationalIncidentEvent,
    OperationalPhaseFact,
    OperationalPlanSnapshot,
    OperationalResourceWindow,
    OperationalResponsibility,
    OperationalTemplate,
    OperationalTemplateVersion,
    OperationalVerification,
    OperationalVerificationEvent,
    OperationCommand,
    PostEventClose,
    PostEventCloseCorrection,
    ReadinessDeviation,
    TemplatePhaseDefinition,
    TemplateReadinessDefinition,
    TemplateResourceNeed,
    TemplateRoleDefinition,
)
from .baseline import due_date
from .errors import OperationsError, conflict, invalid, unavailable
from .models import EventPreparation, PreparationItem
from .normalization import canonical_optional_text, canonical_text
from .services.items import reopen
from .services.shared import check_revision, get_preparation, increment_preparation

P13_SYSTEM_VERSION = "operations-p13-system-v1"
P13_LEGACY_CUTOVER_VERSION = "operations-p13-legacy-cutover-v1"
P13_NAMESPACE = UUID("78caa456-0c69-5c49-a957-10f1ab9d43d0")
RESOLVED_VERIFICATION_STATUSES = {
    OperationalVerification.Status.COMPLETED,
    OperationalVerification.Status.NOT_APPLICABLE,
}


def _json_default(value: object) -> str:
    if isinstance(value, (UUID, Decimal, datetime, date)):
        return str(value)
    raise TypeError(f"Valor no serializable: {type(value)!r}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _uuid(value: object, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(label) from None


def _command_replay(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
) -> OperationCommand | None:
    row = OperationCommand.objects.filter(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
    ).first()
    if row is None:
        return None
    if row.payload_sha256 != _digest(payload):
        raise conflict("idempotency_conflict", "La clave ya se usó con otro contenido.")
    return row


def _complete_command(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
    result_kind: str,
    result_id: UUID,
) -> None:
    OperationCommand.objects.create(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
        payload_sha256=_digest(payload),
        result_kind=result_kind,
        result_id=result_id,
        actor_membership_id=authorization.membership_id,
    )


def _template_payload(version: OperationalTemplateVersion) -> dict[str, object]:
    return {
        "template_id": str(version.template_id),
        "template_version_id": str(version.pk),
        "version": version.version,
        "readiness": [
            {
                "id": str(row.pk),
                "key": row.key,
                "title": row.title,
                "section": row.section,
                "is_required": row.is_required,
                "days_before": row.days_before,
                "role_key": row.role_key,
                "position": row.position,
            }
            for row in version.readiness_definitions.all()
        ],
        "verifications": [
            {
                "id": str(row.pk),
                "key": row.key,
                "phase": row.phase,
                "title": row.title,
                "is_required": row.is_required,
                "role_key": row.role_key,
                "position": row.position,
            }
            for row in version.phase_definitions.all()
        ],
        "roles": [
            {
                "id": str(row.pk),
                "key": row.key,
                "label": row.label,
                "phase": row.phase,
                "position": row.position,
            }
            for row in version.role_definitions.all()
        ],
        "resource_needs": [
            {
                "id": str(row.pk),
                "key": row.key,
                "resource_id": str(row.resource_id),
                "quantity": str(row.quantity),
                "start_anchor": row.start_anchor,
                "start_offset_minutes": row.start_offset_minutes,
                "end_anchor": row.end_anchor,
                "end_offset_minutes": row.end_offset_minutes,
                "position": row.position,
            }
            for row in version.resource_needs.all()
        ],
    }


def _schedule_anchor(
    authority: scheduling_port.OperationsScheduleAuthorityProjection,
    anchor: str,
) -> datetime:
    values: dict[str, datetime] = {
        TemplateResourceNeed.Anchor.OCCUPIED_START: authority.occupied_starts_at,
        TemplateResourceNeed.Anchor.EVENT_START: authority.event_starts_at,
        TemplateResourceNeed.Anchor.EVENT_END: authority.event_ends_at,
        TemplateResourceNeed.Anchor.OCCUPIED_END: authority.occupied_ends_at,
    }
    try:
        return values[anchor]
    except KeyError:
        raise invalid("El ancla temporal de la necesidad no es válida.") from None


def _materialize_window(
    *,
    preparation: EventPreparation,
    snapshot: OperationalPlanSnapshot,
    need: TemplateResourceNeed,
    authority: scheduling_port.OperationsScheduleAuthorityProjection,
    source_kind: str,
    source_version: str,
) -> OperationalResourceWindow:
    starts_at = _schedule_anchor(authority, need.start_anchor) + timedelta(
        minutes=need.start_offset_minutes
    )
    ends_at = _schedule_anchor(authority, need.end_anchor) + timedelta(
        minutes=need.end_offset_minutes
    )
    if starts_at >= ends_at:
        raise conflict(
            "invalid_operation_window", "La ventana operacional no tiene duración válida."
        )
    if starts_at < authority.occupied_starts_at or ends_at > authority.occupied_ends_at:
        raise conflict(
            "operation_window_outside_occupancy",
            "La ventana operacional excede la ocupación autorizada por agenda.",
        )
    identifier = uuid5(P13_NAMESPACE, f"{preparation.pk}:window:{need.pk}:1")
    payload = {
        "preparation_id": preparation.pk,
        "need_id": need.pk,
        "resource_id": need.resource_id,
        "quantity": need.quantity,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "schedule_reservation_revision": authority.reservation_revision,
        "schedule_source_revision": authority.allocation_source_revision,
        "schedule_event_id": authority.source_event_id,
    }
    return OperationalResourceWindow.objects.create(
        id=identifier,
        organization_id=preparation.organization_id,
        preparation=preparation,
        snapshot=snapshot,
        resource_need=need,
        root_reservation_id=authority.root_reservation_id,
        reservation_id=authority.reservation_id,
        schedule_allocation_id=authority.allocation_id,
        schedule_event_id=authority.source_event_id,
        resource_id=need.resource_id,
        quantity=need.quantity,
        required_interval=Range(starts_at, ends_at, bounds="[)"),
        source_kind=source_kind,
        source_version=source_version,
        schedule_reservation_revision=authority.reservation_revision,
        schedule_source_revision=authority.allocation_source_revision,
        idempotency_key=identifier,
        payload_sha256=_digest(payload),
    )


def materialize_operational_plan(
    preparation: EventPreparation,
    *,
    quotation_version_id: UUID,
    starts_at: datetime,
    timezone_name: str,
    occurred_at: datetime,
    source_snapshot: OperationalPlanSnapshot | None = None,
) -> OperationalPlanSnapshot:
    event_type = commercial_port.operation_event_type_snapshot(
        preparation.organization_id, quotation_version_id
    )
    if (
        source_snapshot is not None
        and source_snapshot.source_kind == OperationalPlanSnapshot.SourceKind.LEGACY_CUTOVER
    ):
        legacy_payload = {
            "source_version": source_snapshot.source_version,
            "rescheduled_from_snapshot_id": str(source_snapshot.pk),
            "readiness": [],
            "verifications": [],
            "roles": [],
            "resource_needs": [],
        }
        return OperationalPlanSnapshot.objects.create(
            organization_id=preparation.organization_id,
            preparation=preparation,
            source_kind=OperationalPlanSnapshot.SourceKind.LEGACY_CUTOVER,
            source_version=source_snapshot.source_version,
            event_type_id=event_type.event_type_id,
            event_type_label=event_type.event_type_label,
            canonical_payload=legacy_payload,
            content_sha256=_digest(legacy_payload),
        )
    selected: OperationalTemplateVersion | None = None
    if source_snapshot is not None and source_snapshot.template_version_id is not None:
        selected = OperationalTemplateVersion.objects.prefetch_related(
            "readiness_definitions",
            "phase_definitions",
            "role_definitions",
            "resource_needs",
        ).get(
            organization_id=preparation.organization_id,
            pk=source_snapshot.template_version_id,
        )
    elif source_snapshot is None:
        selected = (
            OperationalTemplateVersion.objects.prefetch_related(
                "readiness_definitions",
                "phase_definitions",
                "role_definitions",
                "resource_needs",
            )
            .filter(
                organization_id=preparation.organization_id,
                template__event_type_id=event_type.event_type_id,
                status=OperationalTemplateVersion.Status.PUBLISHED,
            )
            .order_by("-version", "-created_at", "-id")
            .first()
        )
    if selected is None:
        system_payload: dict[str, object] = {
            "source_version": P13_SYSTEM_VERSION,
            "readiness": [],
            "verifications": [],
            "roles": [],
            "resource_needs": [],
        }
        snapshot = OperationalPlanSnapshot.objects.create(
            organization_id=preparation.organization_id,
            preparation=preparation,
            source_kind=OperationalPlanSnapshot.SourceKind.SYSTEM,
            source_version=P13_SYSTEM_VERSION,
            event_type_id=event_type.event_type_id,
            event_type_label=event_type.event_type_label,
            canonical_payload=system_payload,
            content_sha256=_digest(system_payload),
        )
        return snapshot

    start_position = (
        PreparationItem.objects.filter(preparation=preparation).aggregate(value=Max("position"))[
            "value"
        ]
        or 0
    )
    template_payload = _template_payload(selected)
    materialized_readiness = [
        {
            "definition_id": str(definition.pk),
            "title": definition.title,
            "section": definition.section,
            "is_required": definition.is_required,
            "due_on": due_date(
                starts_at=starts_at,
                timezone_name=timezone_name,
                confirmed_at=occurred_at,
                days_before=definition.days_before,
            ),
            "role_key": definition.role_key,
            "position": start_position + offset,
        }
        for offset, definition in enumerate(selected.readiness_definitions.all(), start=1)
    ]
    template_payload = {
        **template_payload,
        "materialized_readiness": materialized_readiness,
    }
    # JSONField uses the standard JSON encoder. Canonicalize the immutable
    # snapshot before persistence so date/UUID/Decimal values become stable
    # JSON scalars instead of relying only on the digest serializer.
    template_payload = json.loads(_canonical_json(template_payload))
    snapshot = OperationalPlanSnapshot.objects.create(
        organization_id=preparation.organization_id,
        preparation=preparation,
        source_kind=OperationalPlanSnapshot.SourceKind.ORGANIZATION,
        source_version=f"{selected.template_id}:v{selected.version}",
        template_version=selected,
        event_type_id=event_type.event_type_id,
        event_type_label=event_type.event_type_label,
        canonical_payload=template_payload,
        content_sha256=_digest(template_payload),
    )
    PreparationItem.objects.bulk_create(
        [
            PreparationItem(
                id=uuid5(P13_NAMESPACE, f"{preparation.pk}:readiness:{definition.pk}"),
                organization_id=preparation.organization_id,
                preparation=preparation,
                client_request_id=uuid5(
                    P13_NAMESPACE, f"{preparation.pk}:readiness-request:{definition.pk}"
                ),
                source_kind=PreparationItem.SourceKind.P13_TEMPLATE_READINESS,
                template_readiness_definition=definition,
                template_role_key=definition.role_key,
                section=definition.section,
                position=start_position + offset,
                title=definition.title,
                is_required=definition.is_required,
                due_on=due_date(
                    starts_at=starts_at,
                    timezone_name=timezone_name,
                    confirmed_at=occurred_at,
                    days_before=definition.days_before,
                ),
            )
            for offset, definition in enumerate(selected.readiness_definitions.all(), start=1)
        ]
    )
    OperationalVerification.objects.bulk_create(
        [
            OperationalVerification(
                id=uuid5(P13_NAMESPACE, f"{preparation.pk}:verification:{definition.pk}"),
                organization_id=preparation.organization_id,
                preparation=preparation,
                snapshot=snapshot,
                definition=definition,
                source_key=definition.key,
                phase=definition.phase,
                title=definition.title,
                is_required=definition.is_required,
                role_key=definition.role_key,
                position=definition.position,
            )
            for definition in selected.phase_definitions.all()
        ]
    )
    authority = scheduling_port.schedule_authority_for_operations(
        preparation.organization_id, preparation.pk, lock=True
    )
    if authority is None:
        raise conflict(
            "schedule_integrity_conflict",
            "La preparación no tiene una asignación de agenda íntegra.",
        )
    for need in selected.resource_needs.all():
        _materialize_window(
            preparation=preparation,
            snapshot=snapshot,
            need=need,
            authority=authority,
            source_kind=OperationalResourceWindow.SourceKind.ORGANIZATION_TEMPLATE,
            source_version=snapshot.source_version,
        )
    return snapshot


def _definition_payload(values: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "readiness": [],
        "verifications": [],
        "roles": [],
        "resource_needs": [],
    }
    for key in result:
        raw = values.get(key, [])
        if not isinstance(raw, list):
            raise invalid(f"{key} debe ser una lista.")
        result[key] = [dict(item) for item in raw if isinstance(item, dict)]
        if len(result[key]) != len(raw):
            raise invalid(f"{key} contiene una definición inválida.")
    return result


def create_template_version(
    actor: User,
    organization_reference: UUID | str,
    *,
    event_type_id: UUID,
    name: str,
    definitions: dict[str, Any],
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "event_type_id": event_type_id,
        "name": name,
        "definitions": definitions,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_TEMPLATE_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="create_template_version",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            row = OperationalTemplateVersion.objects.get(
                organization_id=authorization.organization_id, pk=replay.result_id
            )
            return template_version_representation(row)
        event_type = catalog_port.event_type_for_operations(
            authorization.organization_id, event_type_id
        )
        if event_type is None or not event_type.is_active:
            raise unavailable("El tipo de evento")
        normalized_name = canonical_text(name, field="El nombre", max_length=160)
        template, _ = OperationalTemplate.objects.select_for_update().get_or_create(
            organization_id=authorization.organization_id,
            event_type_id=event_type_id,
            defaults={
                "name": normalized_name,
                "created_by_membership_id": authorization.membership_id,
            },
        )
        if template.name != normalized_name:
            raise conflict(
                "template_identity_conflict",
                "El tipo de evento ya pertenece a una plantilla con otro nombre.",
            )
        latest = template.versions.aggregate(value=Max("version"))["value"] or 0
        version = OperationalTemplateVersion.objects.create(
            organization_id=authorization.organization_id,
            template=template,
            version=latest + 1,
            created_by_membership_id=authorization.membership_id,
        )
        canonical = _definition_payload(definitions)
        role_keys: set[str] = set()
        for position, item in enumerate(canonical["roles"], start=1):
            key = canonical_text(item.get("key"), field="La clave de rol", max_length=64)
            if key in role_keys:
                raise invalid("Las claves de rol no pueden repetirse.")
            role_keys.add(key)
            role_phase = str(item.get("phase", ""))
            if role_phase and role_phase not in TemplatePhaseDefinition.Phase.values:
                raise invalid("La fase del rol no es válida.")
            TemplateRoleDefinition.objects.create(
                organization_id=authorization.organization_id,
                version=version,
                key=key,
                label=canonical_text(item.get("label"), field="El rol", max_length=120),
                phase=role_phase,
                position=position,
            )
        readiness_keys: set[str] = set()
        for position, item in enumerate(canonical["readiness"], start=1):
            key = canonical_text(item.get("key"), field="La clave", max_length=64)
            if key in readiness_keys:
                raise invalid("Las claves de readiness no pueden repetirse.")
            readiness_keys.add(key)
            role_key = str(item.get("role_key", ""))
            if role_key and role_key not in role_keys:
                raise invalid("El rol requerido no pertenece a la versión.")
            section = str(item.get("section", PreparationItem.Section.DEFINITIONS))
            if section not in PreparationItem.Section.values:
                raise invalid("La sección de readiness no es válida.")
            days_before = int(item.get("days_before", 0))
            if days_before < 0:
                raise invalid("Los días relativos no pueden ser negativos.")
            TemplateReadinessDefinition.objects.create(
                organization_id=authorization.organization_id,
                version=version,
                key=key,
                title=canonical_text(item.get("title"), field="El título", max_length=160),
                section=section,
                is_required=bool(item.get("is_required", True)),
                days_before=days_before,
                role_key=role_key,
                position=position,
            )
        verification_keys: set[str] = set()
        for position, item in enumerate(canonical["verifications"], start=1):
            key = canonical_text(item.get("key"), field="La clave", max_length=64)
            if key in verification_keys:
                raise invalid("Las claves de verificación no pueden repetirse.")
            verification_keys.add(key)
            phase = str(item.get("phase", ""))
            if phase not in TemplatePhaseDefinition.Phase.values:
                raise invalid("La fase de verificación no es válida.")
            role_key = str(item.get("role_key", ""))
            if role_key and role_key not in role_keys:
                raise invalid("El rol requerido no pertenece a la versión.")
            TemplatePhaseDefinition.objects.create(
                organization_id=authorization.organization_id,
                version=version,
                key=key,
                phase=phase,
                title=canonical_text(item.get("title"), field="El título", max_length=160),
                is_required=bool(item.get("is_required", True)),
                role_key=role_key,
                position=position,
            )
        need_keys: set[str] = set()
        for position, item in enumerate(canonical["resource_needs"], start=1):
            key = canonical_text(item.get("key"), field="La clave", max_length=64)
            if key in need_keys:
                raise invalid("Las claves de recurso no pueden repetirse.")
            need_keys.add(key)
            resource_id = _uuid(item.get("resource_id"), "El recurso")
            resource = resources_port.resource_for_operations(authorization, resource_id)
            if resource is None or not resource.is_active:
                raise unavailable("El recurso")
            try:
                quantity = Decimal(str(item.get("quantity")))
            except Exception:
                raise invalid("La cantidad del recurso no es válida.") from None
            if quantity <= 0:
                raise invalid("La cantidad del recurso debe ser positiva.")
            start_anchor = str(item.get("start_anchor", "event_start"))
            end_anchor = str(item.get("end_anchor", "event_end"))
            if (
                start_anchor not in TemplateResourceNeed.Anchor.values
                or end_anchor not in TemplateResourceNeed.Anchor.values
            ):
                raise invalid("El ancla de la ventana no es válida.")
            TemplateResourceNeed.objects.create(
                organization_id=authorization.organization_id,
                version=version,
                key=key,
                resource_id=resource_id,
                quantity=quantity,
                start_anchor=start_anchor,
                start_offset_minutes=int(item.get("start_offset_minutes", 0)),
                end_anchor=end_anchor,
                end_offset_minutes=int(item.get("end_offset_minutes", 0)),
                position=position,
            )
        _complete_command(
            authorization,
            command_type="create_template_version",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_template_version",
            result_id=version.pk,
        )
        return template_version_representation(version)


def publish_template_version(
    actor: User,
    organization_reference: UUID | str,
    *,
    version_id: UUID,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {"version_id": version_id}
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_TEMPLATE_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="publish_template_version",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return template_version_representation(
                OperationalTemplateVersion.objects.get(pk=replay.result_id)
            )
        try:
            row = OperationalTemplateVersion.objects.select_for_update().get(
                organization_id=authorization.organization_id, pk=version_id
            )
        except OperationalTemplateVersion.DoesNotExist:
            raise unavailable("La versión de plantilla") from None
        if row.status != OperationalTemplateVersion.Status.DRAFT:
            raise conflict("invalid_transition", "Solo un borrador puede publicarse.")
        content = _template_payload(row)
        now = timezone.now()
        OperationalTemplateVersion.objects.filter(
            organization_id=authorization.organization_id,
            template_id=row.template_id,
            status=OperationalTemplateVersion.Status.PUBLISHED,
        ).update(status=OperationalTemplateVersion.Status.RETIRED, retired_at=now)
        row.status = OperationalTemplateVersion.Status.PUBLISHED
        row.content_sha256 = _digest(content)
        row.published_at = now
        row.published_by_membership_id = authorization.membership_id
        row.save(
            update_fields=[
                "status",
                "content_sha256",
                "published_at",
                "published_by_membership",
            ]
        )
        _complete_command(
            authorization,
            command_type="publish_template_version",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_template_version",
            result_id=row.pk,
        )
        return template_version_representation(row)


def retire_template_version(
    actor: User,
    organization_reference: UUID | str,
    *,
    version_id: UUID,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {"version_id": version_id}
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_TEMPLATE_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="retire_template_version",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return template_version_representation(
                OperationalTemplateVersion.objects.get(pk=replay.result_id)
            )
        try:
            row = OperationalTemplateVersion.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=version_id,
                status=OperationalTemplateVersion.Status.PUBLISHED,
            )
        except OperationalTemplateVersion.DoesNotExist:
            raise unavailable("La versión publicada") from None
        row.status = OperationalTemplateVersion.Status.RETIRED
        row.retired_at = timezone.now()
        row.save(update_fields=["status", "retired_at"])
        _complete_command(
            authorization,
            command_type="retire_template_version",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_template_version",
            result_id=row.pk,
        )
        return template_version_representation(row)


def template_version_representation(row: OperationalTemplateVersion) -> dict[str, object]:
    return {
        "id": row.pk,
        "template_id": row.template_id,
        "event_type_id": row.template.event_type_id,
        "name": row.template.name,
        "version": row.version,
        "status": row.status,
        "content_sha256": row.content_sha256,
        "published_at": row.published_at,
        "definitions": _template_payload(row),
    }


def snapshot_representation(row: OperationalPlanSnapshot) -> dict[str, object]:
    return {
        "id": row.pk,
        "source_kind": row.source_kind,
        "source_version": row.source_version,
        "event_type_id": row.event_type_id,
        "event_type_label": row.event_type_label,
        "content_sha256": row.content_sha256,
    }


def list_template_versions(
    actor: User, organization_reference: UUID | str
) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_TEMPLATE_READ
    ) as authorization:
        return tuple(
            template_version_representation(row)
            for row in OperationalTemplateVersion.objects.select_related("template")
            .prefetch_related(
                "readiness_definitions",
                "phase_definitions",
                "role_definitions",
                "resource_needs",
            )
            .filter(organization_id=authorization.organization_id)
            .order_by("template__name", "-version", "id")
        )


def adopt_legacy_preparation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    revision: int,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {"reservation_id": reservation_id, "revision": revision}
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="adopt_legacy_preparation",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return snapshot_representation(OperationalPlanSnapshot.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        check_revision(preparation, revision)
        if preparation.status not in {
            EventPreparation.Status.PREPARING,
            EventPreparation.Status.READY,
            EventPreparation.Status.IN_PROGRESS,
        }:
            raise conflict(
                "invalid_transition",
                "Solo una preparación activa puede incorporarse expresamente a P13.",
            )
        if OperationalPlanSnapshot.objects.filter(preparation=preparation).exists():
            raise conflict("already_materialized", "La preparación ya tiene un snapshot P13.")
        event_type = commercial_port.operation_event_type_snapshot(
            authorization.organization_id,
            preparation.reservation.quotation_version_id,
        )
        observed = {
            "source_version": P13_LEGACY_CUTOVER_VERSION,
            "observed_preparation": {
                "status": preparation.status,
                "revision": preparation.revision,
                "baseline_version": preparation.baseline_version,
            },
            "observed_readiness": [
                {
                    "id": str(item.pk),
                    "source_kind": item.source_kind,
                    "baseline_key": item.baseline_key,
                    "status": item.status,
                    "revision": item.revision,
                }
                for item in PreparationItem.objects.filter(preparation=preparation).order_by(
                    "position", "id"
                )
            ],
            "readiness": [],
            "verifications": [],
            "roles": [],
            "resource_needs": [],
        }
        snapshot = OperationalPlanSnapshot.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            source_kind=OperationalPlanSnapshot.SourceKind.LEGACY_CUTOVER,
            source_version=P13_LEGACY_CUTOVER_VERSION,
            event_type_id=event_type.event_type_id,
            event_type_label=event_type.event_type_label,
            canonical_payload=observed,
            content_sha256=_digest(observed),
        )
        _complete_command(
            authorization,
            command_type="adopt_legacy_preparation",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_plan_snapshot",
            result_id=snapshot.pk,
        )
        return snapshot_representation(snapshot)


def _get_advanced_preparation(
    authorization: TenantAuthorization, reservation_id: UUID, *, lock: bool = False
) -> EventPreparation:
    try:
        return get_preparation(authorization.organization_id, reservation_id, lock=lock)
    except OperationsError:
        raise


def update_verification(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    verification_id: UUID,
    revision: int,
    status: str,
    reason: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "verification_id": verification_id,
        "revision": revision,
        "status": status,
        "reason": reason,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_EXECUTE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="update_operational_verification",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            row = OperationalVerification.objects.get(pk=replay.result_id)
            return verification_representation(row)
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        try:
            row = OperationalVerification.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=verification_id,
            )
        except OperationalVerification.DoesNotExist:
            raise unavailable("La verificación") from None
        if row.revision != revision:
            raise conflict("stale_revision", "La verificación cambió. Vuelve a cargarla.")
        if row.status != OperationalVerification.Status.PENDING:
            raise conflict("invalid_transition", "La verificación ya fue resuelta.")
        if status not in RESOLVED_VERIFICATION_STATUSES:
            raise invalid("El estado de verificación no es válido.")
        normalized_reason = canonical_optional_text(reason, field="La razón", max_length=500)
        if status == OperationalVerification.Status.NOT_APPLICABLE and not normalized_reason:
            raise invalid("La razón es obligatoria para no aplica.")
        allowed: dict[str, set[str]] = {
            TemplatePhaseDefinition.Phase.SETUP: {
                EventPreparation.Status.PREPARING,
                EventPreparation.Status.READY,
            },
            TemplatePhaseDefinition.Phase.EXECUTION: {EventPreparation.Status.IN_PROGRESS},
            TemplatePhaseDefinition.Phase.TEARDOWN: {EventPreparation.Status.COMPLETED},
            TemplatePhaseDefinition.Phase.POST_EVENT: {EventPreparation.Status.COMPLETED},
        }
        if preparation.status not in allowed[row.phase]:
            raise conflict("invalid_transition", "La fase no puede resolverse en este estado.")
        now = timezone.now()
        row.status = status
        row.status_reason = normalized_reason
        row.completed_at = now
        row.completed_by_membership_id = authorization.membership_id
        row.revision += 1
        row.save(
            update_fields=[
                "status",
                "status_reason",
                "completed_at",
                "completed_by_membership",
                "revision",
                "updated_at",
            ]
        )
        OperationalVerificationEvent.objects.create(
            organization_id=authorization.organization_id,
            verification=row,
            from_status=OperationalVerification.Status.PENDING,
            to_status=status,
            reason=normalized_reason,
            verification_revision=row.revision,
            actor_membership_id=authorization.membership_id,
            occurred_at=now,
            idempotency_key=idempotency_key,
        )
        _complete_command(
            authorization,
            command_type="update_operational_verification",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_verification",
            result_id=row.pk,
        )
        return verification_representation(row)


def correct_verification(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    verification_id: UUID,
    event_id: UUID,
    revision: int,
    status: str,
    status_reason: str,
    correction_reason: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "verification_id": verification_id,
        "event_id": event_id,
        "revision": revision,
        "status": status,
        "status_reason": status_reason,
        "correction_reason": correction_reason,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_CHANGE_AUTHORIZE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="correct_operational_verification",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return verification_representation(
                OperationalVerification.objects.get(pk=replay.result_id)
            )
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        try:
            row = OperationalVerification.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=verification_id,
            )
            target = OperationalVerificationEvent.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                verification=row,
                pk=event_id,
            )
        except (
            OperationalVerification.DoesNotExist,
            OperationalVerificationEvent.DoesNotExist,
        ):
            raise unavailable("El hecho de verificación") from None
        if row.revision != revision or hasattr(target, "correction"):
            raise conflict("stale_revision", "La verificación o su corrección cambió.")
        if row.status == OperationalVerification.Status.PENDING:
            raise conflict("invalid_transition", "No existe un hecho cumplido que corregir.")
        if status not in RESOLVED_VERIFICATION_STATUSES:
            raise invalid("El estado corregido no es válido.")
        normalized_status_reason = canonical_optional_text(
            status_reason, field="La razón de estado", max_length=500
        )
        if status == OperationalVerification.Status.NOT_APPLICABLE:
            if not normalized_status_reason:
                raise invalid("La razón es obligatoria para no aplica.")
        else:
            normalized_status_reason = ""
        correction = canonical_text(correction_reason, field="La corrección", max_length=500)
        previous = row.status
        now = timezone.now()
        row.status = status
        row.status_reason = normalized_status_reason
        row.completed_at = now
        row.completed_by_membership_id = authorization.membership_id
        row.revision += 1
        row.save(
            update_fields=[
                "status",
                "status_reason",
                "completed_at",
                "completed_by_membership",
                "revision",
                "updated_at",
            ]
        )
        OperationalVerificationEvent.objects.create(
            organization_id=authorization.organization_id,
            verification=row,
            from_status=previous,
            to_status=status,
            reason=normalized_status_reason,
            correction_reason=correction,
            verification_revision=row.revision,
            actor_membership_id=authorization.membership_id,
            occurred_at=now,
            idempotency_key=idempotency_key,
            corrects=target,
        )
        _complete_command(
            authorization,
            command_type="correct_operational_verification",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_verification",
            result_id=row.pk,
        )
        return verification_representation(row)


def _effective_phase_fact(
    preparation: EventPreparation, phase: str, fact_kind: str
) -> OperationalPhaseFact | None:
    original = OperationalPhaseFact.objects.filter(
        preparation=preparation,
        phase=phase,
        fact_kind=fact_kind,
        corrects__isnull=True,
    ).first()
    if original is None:
        return None
    current = original
    while hasattr(current, "correction"):
        current = current.correction
    return current


def record_phase_fact(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    phase: str,
    fact_kind: str,
    revision: int,
    observed_at: datetime | None,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "reservation_id": reservation_id,
        "phase": phase,
        "fact_kind": fact_kind,
        "revision": revision,
        "observed_at": observed_at,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_EXECUTE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="record_operational_phase_fact",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return phase_fact_representation(OperationalPhaseFact.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        check_revision(preparation, revision)
        if phase not in OperationalPhaseFact.Phase.values:
            raise invalid("La fase observable no es válida.")
        if fact_kind not in OperationalPhaseFact.FactKind.values:
            raise invalid("El hecho temporal no es válido.")
        allowed_states = (
            {EventPreparation.Status.PREPARING, EventPreparation.Status.READY}
            if phase == OperationalPhaseFact.Phase.SETUP
            else {EventPreparation.Status.COMPLETED}
        )
        if preparation.status not in allowed_states:
            raise conflict("invalid_transition", "La fase no admite ese hecho temporal.")
        if _effective_phase_fact(preparation, phase, fact_kind) is not None:
            raise conflict("invalid_transition", "El hecho temporal ya fue registrado.")
        effective_at = observed_at or timezone.now()
        started = _effective_phase_fact(preparation, phase, OperationalPhaseFact.FactKind.STARTED)
        if fact_kind == OperationalPhaseFact.FactKind.COMPLETED:
            if started is None:
                raise conflict("invalid_transition", "La fase debe iniciarse antes de finalizar.")
            if effective_at < started.observed_at:
                raise conflict("invalid_transition", "La fase no puede finalizar antes de iniciar.")
        row = OperationalPhaseFact.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            phase=phase,
            fact_kind=fact_kind,
            observed_at=effective_at,
            actor_membership_id=authorization.membership_id,
            preparation_revision=preparation.revision,
            idempotency_key=idempotency_key,
            payload_sha256=_digest(
                {
                    **payload,
                    "effective_observed_at": effective_at,
                    "actor_membership_id": authorization.membership_id,
                    "preparation_revision": preparation.revision,
                }
            ),
        )
        _complete_command(
            authorization,
            command_type="record_operational_phase_fact",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_phase_fact",
            result_id=row.pk,
        )
        return phase_fact_representation(row)


def correct_phase_fact(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    fact_id: UUID,
    revision: int,
    observed_at: datetime,
    reason: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "fact_id": fact_id,
        "revision": revision,
        "observed_at": observed_at,
        "reason": reason,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_CHANGE_AUTHORIZE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="correct_operational_phase_fact",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return phase_fact_representation(OperationalPhaseFact.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        check_revision(preparation, revision)
        try:
            target = OperationalPhaseFact.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=fact_id,
            )
        except OperationalPhaseFact.DoesNotExist:
            raise unavailable("El hecho temporal") from None
        if hasattr(target, "correction"):
            raise conflict("stale_revision", "El hecho temporal ya tiene una corrección.")
        normalized_reason = canonical_text(reason, field="La razón", max_length=500)
        other_kind = (
            OperationalPhaseFact.FactKind.COMPLETED
            if target.fact_kind == OperationalPhaseFact.FactKind.STARTED
            else OperationalPhaseFact.FactKind.STARTED
        )
        other = _effective_phase_fact(preparation, target.phase, other_kind)
        if other is not None and (
            (
                target.fact_kind == OperationalPhaseFact.FactKind.STARTED
                and observed_at > other.observed_at
            )
            or (
                target.fact_kind == OperationalPhaseFact.FactKind.COMPLETED
                and observed_at < other.observed_at
            )
        ):
            raise conflict(
                "invalid_transition", "La corrección produciría una secuencia imposible."
            )
        row = OperationalPhaseFact.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            phase=target.phase,
            fact_kind=target.fact_kind,
            observed_at=observed_at,
            actor_membership_id=authorization.membership_id,
            preparation_revision=preparation.revision,
            idempotency_key=idempotency_key,
            provenance="authorized_correction",
            corrects=target,
            correction_reason=normalized_reason,
            payload_sha256=_digest(payload),
        )
        _complete_command(
            authorization,
            command_type="correct_operational_phase_fact",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_phase_fact",
            result_id=row.pk,
        )
        return phase_fact_representation(row)


def assign_operational_responsibility(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    role_key: str,
    phase: str,
    membership_id: UUID | None,
    revision: int,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "role_key": role_key,
        "phase": phase,
        "membership_id": membership_id,
        "revision": revision,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="assign_operational_responsibility",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return responsibility_representation(
                OperationalResponsibility.objects.get(pk=replay.result_id)
            )
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        check_revision(preparation, revision)
        if preparation.status not in {
            EventPreparation.Status.PREPARING,
            EventPreparation.Status.READY,
            EventPreparation.Status.IN_PROGRESS,
        }:
            raise conflict("invalid_transition", "Las responsabilidades ya no pueden cambiarse.")
        snapshot = OperationalPlanSnapshot.objects.get(preparation=preparation)
        normalized_role = canonical_text(role_key, field="El rol", max_length=64)
        available_roles = {
            str(item.get("key")) for item in snapshot.canonical_payload.get("roles", [])
        }
        if normalized_role not in available_roles:
            raise unavailable("El rol operativo")
        if phase and phase not in TemplatePhaseDefinition.Phase.values:
            raise invalid("La fase de responsabilidad no es válida.")
        if membership_id is not None:
            member = organizations_port.membership_for_operations(
                authorization.organization_id, membership_id
            )
            if member is None or not member.is_active or not member.can_manage_operations:
                raise unavailable("La membresía responsable")
        latest = (
            OperationalResponsibility.objects.filter(
                organization_id=authorization.organization_id,
                preparation=preparation,
                role_key=normalized_role,
                phase=phase,
                superseded_by__isnull=True,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        increment_preparation(preparation, fields=[])
        row = OperationalResponsibility.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            snapshot=snapshot,
            role_key=normalized_role,
            phase=phase,
            membership_id=membership_id,
            supersedes=latest,
            assigned_by_membership_id=authorization.membership_id,
            preparation_revision=preparation.revision,
            idempotency_key=idempotency_key,
        )
        _complete_command(
            authorization,
            command_type="assign_operational_responsibility",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_responsibility",
            result_id=row.pk,
        )
        return responsibility_representation(row)


def _contained_incident_is_close_compatible(
    *, severity: str, impact: str, responsible_membership_id: UUID | None, follow_up: str
) -> bool:
    return (
        severity in {OperationalIncident.Severity.LOW, OperationalIncident.Severity.MEDIUM}
        and responsible_membership_id is not None
        and bool(impact.strip())
        and bool(follow_up.strip())
    )


def _incident_blocks_close(incident: OperationalIncident) -> bool:
    if incident.status == OperationalIncident.Status.OPEN:
        return True
    if incident.status == OperationalIncident.Status.RESOLVED:
        return False
    return not _contained_incident_is_close_compatible(
        severity=incident.severity,
        impact=incident.impact,
        responsible_membership_id=incident.responsible_membership_id,
        follow_up=incident.follow_up,
    )


def _ensure_incident_close_consistency(
    incident: OperationalIncident,
    *,
    severity: str,
    impact: str,
    responsible_membership_id: UUID | None,
    follow_up: str,
) -> None:
    if (
        incident.status == OperationalIncident.Status.CONTAINED
        and PostEventClose.objects.filter(preparation=incident.preparation).exists()
        and not _contained_incident_is_close_compatible(
            severity=severity,
            impact=impact,
            responsible_membership_id=responsible_membership_id,
            follow_up=follow_up,
        )
    ):
        raise conflict(
            "incident_blocks_close",
            "La corrección dejaría el cierre postevento con una incidencia incompatible.",
        )


def open_incident(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    incident_type: str,
    severity: str,
    description: str,
    impact: str,
    responsible_membership_id: UUID | None,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "reservation_id": reservation_id,
        "incident_type": incident_type,
        "severity": severity,
        "description": description,
        "impact": impact,
        "responsible_membership_id": responsible_membership_id,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_INCIDENT_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="open_operational_incident",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return incident_representation(OperationalIncident.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        if incident_type not in OperationalIncident.Type.values:
            raise invalid("El tipo de incidencia no es válido.")
        if severity not in OperationalIncident.Severity.values:
            raise invalid("La severidad no es válida.")
        if responsible_membership_id is not None:
            member = organizations_port.membership_for_operations(
                authorization.organization_id, responsible_membership_id
            )
            if member is None or not member.is_active:
                raise unavailable("La membresía responsable")
        now = timezone.now()
        row = OperationalIncident.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            incident_type=incident_type,
            severity=severity,
            description=canonical_text(description, field="La descripción", max_length=1000),
            impact=canonical_text(impact, field="El impacto", max_length=1000),
            follow_up="",
            responsible_membership_id=responsible_membership_id,
            reported_by_membership_id=authorization.membership_id,
            reported_at=now,
        )
        OperationalIncidentEvent.objects.create(
            organization_id=authorization.organization_id,
            incident=row,
            kind=OperationalIncidentEvent.Kind.OPENED,
            from_status="",
            to_status=OperationalIncident.Status.OPEN,
            severity=row.severity,
            impact=row.impact,
            follow_up="",
            responsible_membership_id=responsible_membership_id,
            actor_membership_id=authorization.membership_id,
            incident_revision=1,
            occurred_at=now,
            idempotency_key=idempotency_key,
        )
        _complete_command(
            authorization,
            command_type="open_operational_incident",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_incident",
            result_id=row.pk,
        )
        return incident_representation(row)


def transition_incident(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    incident_id: UUID,
    revision: int,
    status: str,
    detail: str,
    follow_up: str = "",
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "incident_id": incident_id,
        "revision": revision,
        "status": status,
        "detail": detail,
        "follow_up": follow_up,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_INCIDENT_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="transition_operational_incident",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return incident_representation(OperationalIncident.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        try:
            row = OperationalIncident.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=incident_id,
            )
        except OperationalIncident.DoesNotExist:
            raise unavailable("La incidencia") from None
        if row.revision != revision:
            raise conflict("stale_revision", "La incidencia cambió. Vuelve a cargarla.")
        transitions: dict[str, set[str]] = {
            OperationalIncident.Status.OPEN: {
                OperationalIncident.Status.CONTAINED,
                OperationalIncident.Status.RESOLVED,
            },
            OperationalIncident.Status.CONTAINED: {OperationalIncident.Status.RESOLVED},
            OperationalIncident.Status.RESOLVED: set(),
        }
        if status not in transitions[row.status]:
            raise conflict("invalid_transition", "La transición de incidencia no es válida.")
        old = row.status
        normalized_follow_up = row.follow_up
        if status == OperationalIncident.Status.CONTAINED:
            normalized_follow_up = canonical_optional_text(
                follow_up, field="El seguimiento", max_length=1000
            )
        elif follow_up not in (None, ""):
            raise invalid("El seguimiento explícito solo se registra al contener la incidencia.")
        row.status = status
        row.follow_up = normalized_follow_up
        row.revision += 1
        row.save(update_fields=["status", "follow_up", "revision", "updated_at"])
        kind = (
            OperationalIncidentEvent.Kind.CONTAINED
            if status == OperationalIncident.Status.CONTAINED
            else OperationalIncidentEvent.Kind.RESOLVED
        )
        OperationalIncidentEvent.objects.create(
            organization_id=authorization.organization_id,
            incident=row,
            kind=kind,
            from_status=old,
            to_status=status,
            severity=row.severity,
            impact=row.impact,
            follow_up=row.follow_up,
            detail=canonical_text(detail, field="El detalle", max_length=1000),
            responsible_membership=row.responsible_membership,
            actor_membership_id=authorization.membership_id,
            incident_revision=row.revision,
            occurred_at=timezone.now(),
            idempotency_key=idempotency_key,
        )
        _complete_command(
            authorization,
            command_type="transition_operational_incident",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_incident",
            result_id=row.pk,
        )
        return incident_representation(row)


def amend_incident(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    incident_id: UUID,
    revision: int,
    kind: str,
    impact: str,
    follow_up: str,
    responsible_membership_id: UUID | None,
    detail: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "incident_id": incident_id,
        "revision": revision,
        "kind": kind,
        "impact": impact,
        "follow_up": follow_up,
        "responsible_membership_id": responsible_membership_id,
        "detail": detail,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_INCIDENT_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="amend_operational_incident",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return incident_representation(OperationalIncident.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        try:
            incident = OperationalIncident.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=incident_id,
            )
        except OperationalIncident.DoesNotExist:
            raise unavailable("La incidencia") from None
        if incident.revision != revision:
            raise conflict("stale_revision", "La incidencia cambió. Vuelve a cargarla.")
        if incident.status == OperationalIncident.Status.RESOLVED:
            raise conflict("invalid_transition", "Una incidencia resuelta solo admite corrección.")
        allowed = {
            OperationalIncidentEvent.Kind.REASSIGNED,
            OperationalIncidentEvent.Kind.IMPACT_UPDATED,
            OperationalIncidentEvent.Kind.FOLLOW_UP_UPDATED,
        }
        if kind not in allowed:
            raise invalid("El tipo de actualización de incidencia no es válido.")
        if responsible_membership_id is not None:
            member = organizations_port.membership_for_operations(
                authorization.organization_id, responsible_membership_id
            )
            if member is None or not member.is_active:
                raise unavailable("La membresía responsable")
        normalized_impact = canonical_text(impact, field="El impacto", max_length=1000)
        normalized_follow_up = canonical_optional_text(
            follow_up, field="El seguimiento", max_length=1000
        )
        if kind == OperationalIncidentEvent.Kind.REASSIGNED:
            normalized_impact = incident.impact
            normalized_follow_up = incident.follow_up
        elif kind == OperationalIncidentEvent.Kind.FOLLOW_UP_UPDATED:
            normalized_impact = incident.impact
            responsible_membership_id = incident.responsible_membership_id
        else:
            responsible_membership_id = incident.responsible_membership_id
            normalized_follow_up = incident.follow_up
        _ensure_incident_close_consistency(
            incident,
            severity=incident.severity,
            impact=normalized_impact,
            responsible_membership_id=responsible_membership_id,
            follow_up=normalized_follow_up,
        )
        incident.impact = normalized_impact
        incident.follow_up = normalized_follow_up
        incident.responsible_membership_id = responsible_membership_id
        incident.revision += 1
        incident.save(
            update_fields=[
                "impact",
                "follow_up",
                "responsible_membership",
                "revision",
                "updated_at",
            ]
        )
        OperationalIncidentEvent.objects.create(
            organization_id=authorization.organization_id,
            incident=incident,
            kind=kind,
            from_status=incident.status,
            to_status=incident.status,
            severity=incident.severity,
            impact=incident.impact,
            follow_up=incident.follow_up,
            detail=canonical_text(detail, field="El detalle", max_length=1000),
            responsible_membership_id=incident.responsible_membership_id,
            actor_membership_id=authorization.membership_id,
            incident_revision=incident.revision,
            occurred_at=timezone.now(),
            idempotency_key=idempotency_key,
        )
        _complete_command(
            authorization,
            command_type="amend_operational_incident",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_incident",
            result_id=incident.pk,
        )
        return incident_representation(incident)


def correct_incident_event(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    incident_id: UUID,
    event_id: UUID,
    revision: int,
    severity: str,
    impact: str,
    follow_up: str,
    responsible_membership_id: UUID | None,
    detail: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "incident_id": incident_id,
        "event_id": event_id,
        "revision": revision,
        "severity": severity,
        "impact": impact,
        "follow_up": follow_up,
        "responsible_membership_id": responsible_membership_id,
        "detail": detail,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_INCIDENT_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="correct_operational_incident_event",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return incident_representation(OperationalIncident.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        try:
            incident = OperationalIncident.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=incident_id,
            )
            target = OperationalIncidentEvent.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                incident=incident,
                pk=event_id,
            )
        except (OperationalIncident.DoesNotExist, OperationalIncidentEvent.DoesNotExist):
            raise unavailable("El hecho de incidencia") from None
        if incident.revision != revision or hasattr(target, "correction"):
            raise conflict("stale_revision", "La incidencia o su corrección cambió.")
        if severity not in OperationalIncident.Severity.values:
            raise invalid("La severidad no es válida.")
        if responsible_membership_id is not None:
            member = organizations_port.membership_for_operations(
                authorization.organization_id, responsible_membership_id
            )
            if member is None or not member.is_active:
                raise unavailable("La membresía responsable")
        normalized_impact = canonical_text(impact, field="El impacto", max_length=1000)
        normalized_follow_up = canonical_optional_text(
            follow_up, field="El seguimiento", max_length=1000
        )
        _ensure_incident_close_consistency(
            incident,
            severity=severity,
            impact=normalized_impact,
            responsible_membership_id=responsible_membership_id,
            follow_up=normalized_follow_up,
        )
        incident.severity = severity
        incident.impact = normalized_impact
        incident.follow_up = normalized_follow_up
        incident.responsible_membership_id = responsible_membership_id
        incident.revision += 1
        incident.save(
            update_fields=[
                "severity",
                "impact",
                "follow_up",
                "responsible_membership",
                "revision",
                "updated_at",
            ]
        )
        OperationalIncidentEvent.objects.create(
            organization_id=authorization.organization_id,
            incident=incident,
            kind=OperationalIncidentEvent.Kind.CORRECTED,
            from_status=incident.status,
            to_status=incident.status,
            severity=severity,
            impact=incident.impact,
            follow_up=incident.follow_up,
            detail=canonical_text(detail, field="La corrección", max_length=1000),
            responsible_membership_id=responsible_membership_id,
            actor_membership_id=authorization.membership_id,
            incident_revision=incident.revision,
            occurred_at=timezone.now(),
            idempotency_key=idempotency_key,
            corrects=target,
        )
        _complete_command(
            authorization,
            command_type="correct_operational_incident_event",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_incident",
            result_id=incident.pk,
        )
        return incident_representation(incident)


def propose_change(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    scope: str,
    target_id: UUID,
    proposed_payload: dict[str, object],
    reason: str,
    impact: str,
    revision: int,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "scope": scope,
        "target_id": target_id,
        "proposed_payload": proposed_payload,
        "reason": reason,
        "impact": impact,
        "revision": revision,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="propose_operational_change",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return change_representation(OperationalChangeProposal.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        check_revision(preparation, revision)
        if preparation.status not in {
            EventPreparation.Status.PREPARING,
            EventPreparation.Status.READY,
            EventPreparation.Status.IN_PROGRESS,
        }:
            raise conflict("invalid_transition", "La operación ya no admite cambios propuestos.")
        if scope not in OperationalChangeProposal.Scope.values:
            raise invalid("El alcance del cambio no es válido.")
        before: dict[str, object] = {}
        if scope == OperationalChangeProposal.Scope.READINESS:
            if preparation.status not in {
                EventPreparation.Status.PREPARING,
                EventPreparation.Status.READY,
            }:
                raise conflict(
                    "invalid_transition",
                    "El readiness solo puede desviarse durante preparación.",
                )
            try:
                item = PreparationItem.objects.get(
                    organization_id=authorization.organization_id,
                    preparation=preparation,
                    pk=target_id,
                    source_kind=PreparationItem.SourceKind.P13_TEMPLATE_READINESS,
                )
            except PreparationItem.DoesNotExist:
                raise unavailable("El readiness de plantilla") from None
            before = {
                "title": item.title,
                "section": item.section,
                "is_required": item.is_required,
                "due_on": item.due_on,
                "template_role_key": item.template_role_key,
                "position": item.position,
            }
        elif scope == OperationalChangeProposal.Scope.VERIFICATION:
            try:
                verification = OperationalVerification.objects.get(
                    organization_id=authorization.organization_id,
                    preparation=preparation,
                    pk=target_id,
                    status=OperationalVerification.Status.PENDING,
                )
            except OperationalVerification.DoesNotExist:
                raise unavailable("La verificación pendiente") from None
            before = {
                "title": verification.title,
                "is_required": verification.is_required,
                "role_key": verification.role_key,
            }
        elif scope == OperationalChangeProposal.Scope.RESPONSIBILITY:
            try:
                responsibility = OperationalResponsibility.objects.get(
                    organization_id=authorization.organization_id,
                    preparation=preparation,
                    pk=target_id,
                    superseded_by__isnull=True,
                )
            except OperationalResponsibility.DoesNotExist:
                raise unavailable("La responsabilidad vigente") from None
            before = {
                "role_key": responsibility.role_key,
                "phase": responsibility.phase,
                "membership_id": responsibility.membership_id,
            }
        elif scope == OperationalChangeProposal.Scope.RESOURCE_NEED:
            try:
                snapshot = OperationalPlanSnapshot.objects.get(
                    organization_id=authorization.organization_id,
                    preparation=preparation,
                    pk=target_id,
                )
            except OperationalPlanSnapshot.DoesNotExist:
                raise unavailable("El snapshot operacional") from None
            allowed = {
                "resource_id",
                "quantity",
                "start_anchor",
                "start_offset_minutes",
                "end_anchor",
                "end_offset_minutes",
            }
            if set(proposed_payload) != allowed:
                raise invalid("La necesidad de recurso requiere una definición temporal completa.")
            before = {"snapshot_id": snapshot.pk}
        elif scope == OperationalChangeProposal.Scope.RESOURCE_WINDOW:
            try:
                window = OperationalResourceWindow.objects.select_related(
                    "resource_need", "authorization_decision__proposal"
                ).get(
                    organization_id=authorization.organization_id,
                    preparation=preparation,
                    pk=target_id,
                    successor__isnull=True,
                )
            except OperationalResourceWindow.DoesNotExist:
                raise unavailable("La ventana operacional vigente") from None
            authorization_decision = window.authorization_decision
            source = (
                authorization_decision.proposal.proposed_payload
                if authorization_decision is not None
                else {}
            )
            need = window.resource_need
            before = {
                "resource_id": window.resource_id,
                "quantity": window.quantity,
                "start_anchor": (
                    need.start_anchor if need is not None else source.get("start_anchor")
                ),
                "start_offset_minutes": (
                    need.start_offset_minutes
                    if need is not None
                    else source.get("start_offset_minutes")
                ),
                "end_anchor": need.end_anchor if need is not None else source.get("end_anchor"),
                "end_offset_minutes": (
                    need.end_offset_minutes
                    if need is not None
                    else source.get("end_offset_minutes")
                ),
            }
        before = json.loads(_canonical_json(before))
        normalized_proposed = json.loads(_canonical_json(proposed_payload))
        row = OperationalChangeProposal.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            scope=scope,
            target_id=target_id,
            before_payload=before,
            proposed_payload=normalized_proposed,
            reason=canonical_text(reason, field="La razón", max_length=1000),
            impact=canonical_text(impact, field="El impacto", max_length=1000),
            proposed_by_membership_id=authorization.membership_id,
            expected_preparation_revision=revision,
            idempotency_key=idempotency_key,
            payload_sha256=_digest(payload),
        )
        _complete_command(
            authorization,
            command_type="propose_operational_change",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_change_proposal",
            result_id=row.pk,
        )
        return change_representation(row)


def decide_change(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    proposal_id: UUID,
    approved: bool,
    reason: str,
    revision: int,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "proposal_id": proposal_id,
        "approved": approved,
        "reason": reason,
        "revision": revision,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_CHANGE_AUTHORIZE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="decide_operational_change",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return change_representation(OperationalChangeProposal.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        check_revision(preparation, revision)
        try:
            proposal = OperationalChangeProposal.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=proposal_id,
                status=OperationalChangeProposal.Status.PENDING,
            )
        except OperationalChangeProposal.DoesNotExist:
            raise unavailable("La propuesta pendiente") from None
        if preparation.status not in {
            EventPreparation.Status.PREPARING,
            EventPreparation.Status.READY,
            EventPreparation.Status.IN_PROGRESS,
        }:
            raise conflict("invalid_transition", "La operación ya no admite cambios.")
        if (
            approved
            and proposal.scope == OperationalChangeProposal.Scope.READINESS
            and preparation.status
            not in {EventPreparation.Status.PREPARING, EventPreparation.Status.READY}
        ):
            raise conflict(
                "invalid_transition", "El readiness solo puede desviarse durante preparación."
            )
        now = timezone.now()
        decision = OperationalChangeDecision.objects.create(
            organization_id=authorization.organization_id,
            proposal=proposal,
            approved=approved,
            reason=canonical_text(reason, field="La decisión", max_length=1000),
            decided_by_membership_id=authorization.membership_id,
            expected_preparation_revision=revision,
            idempotency_key=idempotency_key,
            payload_sha256=_digest(payload),
            decided_at=now,
        )
        proposal.status = (
            OperationalChangeProposal.Status.APPROVED
            if approved
            else OperationalChangeProposal.Status.REJECTED
        )
        proposal.save(update_fields=["status"])
        if approved and proposal.scope == OperationalChangeProposal.Scope.READINESS:
            item = PreparationItem.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=proposal.target_id,
                source_kind=PreparationItem.SourceKind.P13_TEMPLATE_READINESS,
            )
            allowed = {
                "title",
                "section",
                "is_required",
                "due_on",
                "template_role_key",
                "position",
            }
            if not set(proposal.proposed_payload).issubset(allowed):
                raise invalid("La desviación contiene campos no autorizables.")
            before = {
                "title": item.title,
                "section": item.section,
                "is_required": item.is_required,
                "due_on": item.due_on,
                "template_role_key": item.template_role_key,
                "position": item.position,
            }
            for field, value in proposal.proposed_payload.items():
                setattr(item, field, value)
            item.revision += 1
            item.save(update_fields=[*proposal.proposed_payload.keys(), "revision", "updated_at"])
            effective = {
                "title": item.title,
                "section": item.section,
                "is_required": item.is_required,
                "due_on": item.due_on,
                "template_role_key": item.template_role_key,
                "position": item.position,
            }
            ReadinessDeviation.objects.create(
                organization_id=authorization.organization_id,
                item=item,
                decision=decision,
                before_payload=json.loads(_canonical_json(before)),
                effective_payload=json.loads(_canonical_json(effective)),
                reason=proposal.reason,
                item_revision=item.revision,
                payload_sha256=_digest(effective),
            )
            if preparation.status == EventPreparation.Status.READY:
                increment_preparation(preparation, fields=[])
                reopen(preparation, authorization.membership_id, now)
            else:
                increment_preparation(preparation, fields=[])
        elif approved and proposal.scope == OperationalChangeProposal.Scope.VERIFICATION:
            verification = OperationalVerification.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=proposal.target_id,
                status=OperationalVerification.Status.PENDING,
            )
            allowed = {"title", "is_required", "role_key"}
            if not set(proposal.proposed_payload).issubset(allowed):
                raise invalid("El cambio de verificación contiene campos no autorizables.")
            for field, value in proposal.proposed_payload.items():
                setattr(verification, field, value)
            verification.revision += 1
            verification.save(
                update_fields=[*proposal.proposed_payload.keys(), "revision", "updated_at"]
            )
            increment_preparation(preparation, fields=[])
        elif approved and proposal.scope == OperationalChangeProposal.Scope.RESPONSIBILITY:
            previous = OperationalResponsibility.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=proposal.target_id,
                superseded_by__isnull=True,
            )
            membership_value = proposal.proposed_payload.get(
                "membership_id", previous.membership_id
            )
            membership_id = (
                None
                if membership_value is None
                else _uuid(membership_value, "La membresía responsable")
            )
            if membership_id is not None:
                member = organizations_port.membership_for_operations(
                    authorization.organization_id, membership_id
                )
                if member is None or not member.is_active or not member.can_manage_operations:
                    raise unavailable("La membresía responsable")
            increment_preparation(preparation, fields=[])
            OperationalResponsibility.objects.create(
                organization_id=authorization.organization_id,
                preparation=preparation,
                snapshot=previous.snapshot,
                role_key=previous.role_key,
                phase=previous.phase,
                membership_id=membership_id,
                supersedes=previous,
                assigned_by_membership_id=authorization.membership_id,
                preparation_revision=preparation.revision,
                idempotency_key=idempotency_key,
            )
        elif approved and proposal.scope == OperationalChangeProposal.Scope.RESOURCE_NEED:
            snapshot = OperationalPlanSnapshot.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=proposal.target_id,
            )
            values = proposal.proposed_payload
            start_anchor = str(values.get("start_anchor", ""))
            end_anchor = str(values.get("end_anchor", ""))
            if (
                start_anchor not in TemplateResourceNeed.Anchor.values
                or end_anchor not in TemplateResourceNeed.Anchor.values
            ):
                raise invalid("La necesidad requiere anclas temporales válidas.")
            authority = scheduling_port.schedule_authority_for_operations(
                authorization.organization_id, preparation.pk, lock=True
            )
            if authority is None:
                raise conflict("schedule_integrity_conflict", "La agenda autoritativa cambió.")
            starts_at = _schedule_anchor(authority, start_anchor) + timedelta(
                minutes=int(values.get("start_offset_minutes", 0))
            )
            ends_at = _schedule_anchor(authority, end_anchor) + timedelta(
                minutes=int(values.get("end_offset_minutes", 0))
            )
            if (
                starts_at >= ends_at
                or starts_at < authority.occupied_starts_at
                or ends_at > authority.occupied_ends_at
            ):
                raise conflict(
                    "operation_window_outside_occupancy",
                    "La ventana autorizada excede la ocupación de Scheduling.",
                )
            resource_id = _uuid(values.get("resource_id"), "El recurso")
            quantity = Decimal(str(values.get("quantity")))
            if quantity <= 0:
                raise invalid("La cantidad del recurso debe ser positiva.")
            window_payload = {
                **values,
                "snapshot_id": snapshot.pk,
                "decision_id": decision.pk,
                "starts_at": starts_at,
                "ends_at": ends_at,
            }
            OperationalResourceWindow.objects.create(
                organization_id=authorization.organization_id,
                preparation=preparation,
                snapshot=snapshot,
                resource_need=None,
                root_reservation_id=authority.root_reservation_id,
                reservation_id=authority.reservation_id,
                schedule_allocation_id=authority.allocation_id,
                schedule_event_id=authority.source_event_id,
                resource_id=resource_id,
                quantity=quantity,
                required_interval=Range(starts_at, ends_at, bounds="[)"),
                window_revision=1,
                predecessor=None,
                source_kind=OperationalResourceWindow.SourceKind.AUTHORIZED_CHANGE,
                source_version=f"{snapshot.source_version}:change:{decision.pk}",
                authorization_decision=decision,
                schedule_reservation_revision=authority.reservation_revision,
                schedule_source_revision=authority.allocation_source_revision,
                idempotency_key=idempotency_key,
                payload_sha256=_digest(window_payload),
            )
            increment_preparation(preparation, fields=[])
        elif approved and proposal.scope == OperationalChangeProposal.Scope.RESOURCE_WINDOW:
            previous_window = OperationalResourceWindow.objects.select_for_update(of=("self",)).get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=proposal.target_id,
                successor__isnull=True,
            )
            values = {**proposal.before_payload, **proposal.proposed_payload}
            start_anchor = str(values.get("start_anchor", ""))
            end_anchor = str(values.get("end_anchor", ""))
            if (
                start_anchor not in TemplateResourceNeed.Anchor.values
                or end_anchor not in TemplateResourceNeed.Anchor.values
            ):
                raise invalid("El cambio requiere anclas temporales válidas.")
            authority = scheduling_port.schedule_authority_for_operations(
                authorization.organization_id, preparation.pk, lock=True
            )
            if authority is None:
                raise conflict("schedule_integrity_conflict", "La agenda autoritativa cambió.")
            starts_at = _schedule_anchor(authority, start_anchor) + timedelta(
                minutes=int(values.get("start_offset_minutes", 0))
            )
            ends_at = _schedule_anchor(authority, end_anchor) + timedelta(
                minutes=int(values.get("end_offset_minutes", 0))
            )
            if (
                starts_at >= ends_at
                or starts_at < authority.occupied_starts_at
                or ends_at > authority.occupied_ends_at
            ):
                raise conflict(
                    "operation_window_outside_occupancy",
                    "La ventana autorizada excede la ocupación de Scheduling.",
                )
            resource_id = _uuid(values.get("resource_id"), "El recurso")
            quantity = Decimal(str(values.get("quantity")))
            window_payload = {
                **values,
                "predecessor_id": previous_window.pk,
                "decision_id": decision.pk,
                "starts_at": starts_at,
                "ends_at": ends_at,
            }
            OperationalResourceWindow.objects.create(
                organization_id=authorization.organization_id,
                preparation=preparation,
                snapshot=previous_window.snapshot,
                resource_need=None,
                root_reservation_id=authority.root_reservation_id,
                reservation_id=authority.reservation_id,
                schedule_allocation_id=authority.allocation_id,
                schedule_event_id=authority.source_event_id,
                resource_id=resource_id,
                quantity=quantity,
                required_interval=Range(starts_at, ends_at, bounds="[)"),
                window_revision=previous_window.window_revision + 1,
                predecessor=previous_window,
                source_kind=OperationalResourceWindow.SourceKind.AUTHORIZED_CHANGE,
                source_version=f"{previous_window.snapshot.source_version}:change:{decision.pk}",
                authorization_decision=decision,
                schedule_reservation_revision=authority.reservation_revision,
                schedule_source_revision=authority.allocation_source_revision,
                idempotency_key=idempotency_key,
                payload_sha256=_digest(window_payload),
            )
            increment_preparation(preparation, fields=[])
        _complete_command(
            authorization,
            command_type="decide_operational_change",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="operational_change_proposal",
            result_id=proposal.pk,
        )
        return change_representation(proposal)


def reserve_operational_window(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    window_id: UUID,
    reason: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        try:
            window = OperationalResourceWindow.objects.get(
                organization_id=authorization.organization_id,
                preparation_id=reservation_id,
                pk=window_id,
                successor__isnull=True,
            )
        except OperationalResourceWindow.DoesNotExist:
            raise unavailable("La ventana operacional") from None
    requirement_id = resources_port.create_requirement_for_window(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        resource_id=window.resource_id,
        quantity=window.quantity,
        reason=reason,
        idempotency_key=idempotency_key,
        operational_window_id=window.pk,
    )
    return {"requirement_id": requirement_id, "window_id": window.pk}


def attach_operational_evidence(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    target_kind: str,
    target_id: UUID,
    display_name: str,
    declared_media_type: str,
    source: Any,
    correlation_id: str,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "reservation_id": reservation_id,
        "target_kind": target_kind,
        "target_id": target_id,
        "display_name": display_name,
        "declared_media_type": declared_media_type,
        "correlation_id": correlation_id,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_EVIDENCE_MANAGE
        ) as authorization,
        transaction.atomic(),
    ):
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        if target_kind not in OperationalEvidence.TargetKind.values:
            raise invalid("El destino de evidencia no es válido.")
        if target_kind == OperationalEvidence.TargetKind.GENERAL:
            target_exists = target_id == preparation.pk
        elif target_kind == OperationalEvidence.TargetKind.VERIFICATION:
            target_exists = OperationalVerification.objects.filter(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=target_id,
            ).exists()
        elif target_kind == OperationalEvidence.TargetKind.INCIDENT:
            target_exists = OperationalIncident.objects.filter(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=target_id,
            ).exists()
        elif target_kind == OperationalEvidence.TargetKind.CHANGE:
            target_exists = OperationalChangeProposal.objects.filter(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=target_id,
            ).exists()
        else:
            target_exists = PostEventClose.objects.filter(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=target_id,
            ).exists()
        if not target_exists:
            raise unavailable("El destino de evidencia")
        existing = OperationalEvidence.objects.filter(
            organization_id=authorization.organization_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            if existing.payload_sha256 != _digest(payload):
                raise conflict("idempotency_conflict", "La clave ya se usó con otro contenido.")
            return evidence_representation(existing)
        file_projection = documents_port.receive_operational_evidence(
            authorization,
            preparation_id=preparation.pk,
            display_name=display_name,
            declared_media_type=declared_media_type,
            source=source,
            correlation_id=correlation_id,
        )
        row = OperationalEvidence.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            target_kind=target_kind,
            target_id=target_id,
            document_file_id=file_projection.id,
            linked_by_membership_id=authorization.membership_id,
            idempotency_key=idempotency_key,
            payload_sha256=_digest(payload),
        )
        return evidence_representation(row)


def download_operational_evidence(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    file_id: UUID,
) -> tuple[bytes, str, str]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_EVIDENCE_READ
    ) as authorization:
        preparation = _get_advanced_preparation(authorization, reservation_id)
        if not OperationalEvidence.objects.filter(
            organization_id=authorization.organization_id,
            preparation=preparation,
            document_file_id=file_id,
        ).exists():
            raise unavailable("La evidencia operacional")
        try:
            return documents_port.download_operational_evidence(
                authorization, preparation_id=preparation.pk, file_id=file_id
            )
        except documents_port.DocumentsPortError as error:
            raise OperationsError(error.code, error.detail, status=error.status_code) from error


def close_post_event(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    revision: int,
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {"reservation_id": reservation_id, "revision": revision}
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_CLOSE
        ) as authorization,
        transaction.atomic(),
    ):
        replay = _command_replay(
            authorization,
            command_type="close_post_event",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return close_representation(PostEventClose.objects.get(pk=replay.result_id))
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        if preparation.status != EventPreparation.Status.COMPLETED:
            raise conflict("invalid_transition", "La ejecución todavía no fue completada.")
        check_revision(preparation, revision)
        pending = OperationalVerification.objects.filter(
            organization_id=authorization.organization_id,
            preparation=preparation,
            phase__in=[
                TemplatePhaseDefinition.Phase.TEARDOWN,
                TemplatePhaseDefinition.Phase.POST_EVENT,
            ],
            is_required=True,
            status=OperationalVerification.Status.PENDING,
        ).exists()
        if pending:
            raise conflict("post_event_pending", "Existen verificaciones postevento pendientes.")
        phase_fact_gate(preparation, TemplatePhaseDefinition.Phase.TEARDOWN)
        if OperationalChangeProposal.objects.filter(
            organization_id=authorization.organization_id,
            preparation=preparation,
            status=OperationalChangeProposal.Status.PENDING,
        ).exists():
            raise conflict("post_event_pending", "Existen cambios pendientes de decisión.")
        incidents = tuple(
            OperationalIncident.objects.filter(
                organization_id=authorization.organization_id, preparation=preparation
            )
        )
        if any(_incident_blocks_close(row) for row in incidents):
            raise conflict("incident_blocks_close", "Existen incidencias incompatibles con cierre.")
        resource_rows = resources_port.operational_resource_state(authorization, reservation_id)
        resource_incident_ids = {
            row.pk for row in incidents if row.incident_type == OperationalIncident.Type.RESOURCE
        }
        clean_document_ids = {
            row.id
            for row in documents_port.list_operational_evidence(authorization, preparation.pk)
            if row.state == "clean"
        }
        resource_incident_evidence = OperationalEvidence.objects.filter(
            organization_id=authorization.organization_id,
            preparation=preparation,
            target_kind=OperationalEvidence.TargetKind.INCIDENT,
            target_id__in=resource_incident_ids,
            document_file_id__in=clean_document_ids,
        ).exists()
        resource_change_exists = OperationalChangeDecision.objects.filter(
            organization_id=authorization.organization_id,
            proposal__preparation=preparation,
            proposal__scope__in=[
                OperationalChangeProposal.Scope.RESOURCE_NEED,
                OperationalChangeProposal.Scope.RESOURCE_WINDOW,
            ],
            approved=True,
        ).exists()
        for requirement in resource_rows:
            if requirement.status == "open":
                raise conflict("resources_block_close", "Existe un requerimiento abierto.")
            if requirement.status == "shortage" and not resource_incident_evidence:
                raise conflict(
                    "resources_block_close",
                    "El faltante histórico requiere incidencia y evidencia explícitas.",
                )
            if any(item.status in {"reserved", "custody"} for item in requirement.assignments):
                raise conflict(
                    "resources_block_close", "Existe reserva o custodia física pendiente."
                )
            if any(
                item.status in {"released", "cancelled"} for item in requirement.assignments
            ) and not (resource_incident_ids or resource_change_exists):
                raise conflict(
                    "resources_block_close",
                    "Un recurso no utilizado requiere incidencia o cambio autorizado.",
                )
        snapshot = {
            "preparation": {
                "id": str(preparation.pk),
                "revision": preparation.revision,
                "completed_at": preparation.completed_at,
            },
            "verifications": [
                verification_representation(row)
                for row in OperationalVerification.objects.filter(preparation=preparation)
            ],
            "incidents": [incident_representation(row) for row in incidents],
            "resources": [requirement_representation(row) for row in resource_rows],
            "evidence_ids": [
                str(value)
                for value in OperationalEvidence.objects.filter(
                    preparation=preparation
                ).values_list("document_file_id", flat=True)
            ],
        }
        snapshot = json.loads(_canonical_json(snapshot))
        row = PostEventClose.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            closed_by_membership_id=authorization.membership_id,
            closed_at=timezone.now(),
            preparation_revision=preparation.revision,
            source_snapshot=snapshot,
            source_sha256=_digest(snapshot),
            idempotency_key=idempotency_key,
        )
        _complete_command(
            authorization,
            command_type="close_post_event",
            idempotency_key=idempotency_key,
            payload=payload,
            result_kind="post_event_close",
            result_id=row.pk,
        )
        return close_representation(row)


def correct_post_event_close(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    close_id: UUID,
    reason: str,
    correction_payload: dict[str, object],
    idempotency_key: UUID,
) -> dict[str, object]:
    payload = {
        "close_id": close_id,
        "reason": reason,
        "correction_payload": correction_payload,
    }
    with (
        authorized_tenant_scope(
            actor, organization_reference, Capability.OPERATION_CLOSE
        ) as authorization,
        transaction.atomic(),
    ):
        existing = PostEventCloseCorrection.objects.filter(
            organization_id=authorization.organization_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            if existing.payload_sha256 != _digest(payload):
                raise conflict("idempotency_conflict", "La clave ya se usó con otro contenido.")
            return {
                "id": existing.pk,
                "close_id": existing.close_id,
                "created_at": existing.created_at,
            }
        preparation = _get_advanced_preparation(authorization, reservation_id, lock=True)
        try:
            close = PostEventClose.objects.get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=close_id,
            )
        except PostEventClose.DoesNotExist:
            raise unavailable("El cierre postevento") from None
        row = PostEventCloseCorrection.objects.create(
            organization_id=authorization.organization_id,
            close=close,
            reason=canonical_text(reason, field="La razón", max_length=1000),
            correction_payload=json.loads(_canonical_json(correction_payload)),
            payload_sha256=_digest(payload),
            corrected_by_membership_id=authorization.membership_id,
            idempotency_key=idempotency_key,
        )
        return {"id": row.pk, "close_id": row.close_id, "created_at": row.created_at}


def verification_gate(preparation: EventPreparation, phase: str) -> None:
    if OperationalVerification.objects.filter(
        organization_id=preparation.organization_id,
        preparation=preparation,
        phase=phase,
        is_required=True,
        status=OperationalVerification.Status.PENDING,
    ).exists():
        raise conflict(
            "phase_verifications_pending", "Existen verificaciones obligatorias pendientes."
        )


def phase_fact_gate(preparation: EventPreparation, phase: str) -> None:
    timeline_required = (
        OperationalVerification.objects.filter(preparation=preparation, phase=phase).exists()
        or OperationalPhaseFact.objects.filter(preparation=preparation, phase=phase).exists()
    )
    if timeline_required and (
        _effective_phase_fact(preparation, phase, OperationalPhaseFact.FactKind.STARTED) is None
        or _effective_phase_fact(preparation, phase, OperationalPhaseFact.FactKind.COMPLETED)
        is None
    ):
        raise conflict("phase_timeline_pending", "La fase observada todavía no fue finalizada.")


def operational_window_for_resources_projection(
    organization_id: UUID, window_id: UUID, *, lock: bool = False
) -> OperationalWindowProjection | None:
    rows = OperationalResourceWindow.objects.all()
    if lock:
        rows = rows.select_for_update(of=("self",))
    row = rows.filter(organization_id=organization_id, pk=window_id, successor__isnull=True).first()
    if row is None:
        return None
    return OperationalWindowProjection(
        id=row.pk,
        organization_id=row.organization_id,
        preparation_id=row.preparation_id,
        root_reservation_id=row.root_reservation_id,
        reservation_id=row.reservation_id,
        resource_id=row.resource_id,
        quantity=row.quantity,
        starts_at=row.required_interval.lower,
        ends_at=row.required_interval.upper,
        window_revision=row.window_revision,
        source_kind=row.source_kind,
        source_version=row.source_version,
        schedule_allocation_id=row.schedule_allocation_id,
        schedule_event_id=row.schedule_event_id,
        schedule_reservation_revision=row.schedule_reservation_revision,
        schedule_source_revision=row.schedule_source_revision,
        payload_sha256=row.payload_sha256,
    )


@dataclass(frozen=True, slots=True)
class OperationalWindowProjection:
    id: UUID
    organization_id: UUID
    preparation_id: UUID
    root_reservation_id: UUID
    reservation_id: UUID
    resource_id: UUID
    quantity: Decimal
    starts_at: datetime
    ends_at: datetime
    window_revision: int
    source_kind: str
    source_version: str
    schedule_allocation_id: UUID
    schedule_event_id: UUID
    schedule_reservation_revision: int
    schedule_source_revision: int
    payload_sha256: str


def verification_representation(row: OperationalVerification) -> dict[str, object]:
    return {
        "id": row.pk,
        "source_key": row.source_key,
        "phase": row.phase,
        "title": row.title,
        "is_required": row.is_required,
        "role_key": row.role_key,
        "position": row.position,
        "status": row.status,
        "status_reason": row.status_reason,
        "completed_at": row.completed_at,
        "completed_by_membership_id": row.completed_by_membership_id,
        "revision": row.revision,
        "events": [
            {
                "id": event.pk,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "reason": event.reason,
                "correction_reason": event.correction_reason,
                "corrects_id": event.corrects_id,
                "occurred_at": event.occurred_at,
            }
            for event in row.events.order_by("verification_revision", "id")
        ],
    }


def phase_fact_representation(row: OperationalPhaseFact) -> dict[str, object]:
    return {
        "id": row.pk,
        "phase": row.phase,
        "fact_kind": row.fact_kind,
        "observed_at": row.observed_at,
        "actor_membership_id": row.actor_membership_id,
        "preparation_revision": row.preparation_revision,
        "provenance": row.provenance,
        "corrects_id": row.corrects_id,
        "correction_reason": row.correction_reason,
    }


def responsibility_representation(row: OperationalResponsibility) -> dict[str, object]:
    return {
        "id": row.pk,
        "role_key": row.role_key,
        "phase": row.phase,
        "membership_id": row.membership_id,
        "supersedes_id": row.supersedes_id,
        "assigned_by_membership_id": row.assigned_by_membership_id,
        "preparation_revision": row.preparation_revision,
    }


def incident_representation(row: OperationalIncident) -> dict[str, object]:
    return {
        "id": row.pk,
        "incident_type": row.incident_type,
        "severity": row.severity,
        "status": row.status,
        "description": row.description,
        "impact": row.impact,
        "follow_up": row.follow_up,
        "responsible_membership_id": row.responsible_membership_id,
        "reported_by_membership_id": row.reported_by_membership_id,
        "reported_at": row.reported_at,
        "revision": row.revision,
        "events": [
            {
                "id": event.pk,
                "kind": event.kind,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "severity": event.severity,
                "impact": event.impact,
                "follow_up": event.follow_up,
                "detail": event.detail,
                "responsible_membership_id": event.responsible_membership_id,
                "occurred_at": event.occurred_at,
                "corrects_id": event.corrects_id,
            }
            for event in row.events.order_by("incident_revision", "id")
        ],
    }


def change_representation(row: OperationalChangeProposal) -> dict[str, object]:
    decision = getattr(row, "decision", None)
    return {
        "id": row.pk,
        "scope": row.scope,
        "target_id": row.target_id,
        "before": row.before_payload,
        "proposed": row.proposed_payload,
        "reason": row.reason,
        "impact": row.impact,
        "status": row.status,
        "proposed_by_membership_id": row.proposed_by_membership_id,
        "decision": None
        if decision is None
        else {
            "id": decision.pk,
            "approved": decision.approved,
            "reason": decision.reason,
            "decided_by_membership_id": decision.decided_by_membership_id,
            "decided_at": decision.decided_at,
        },
    }


def window_representation(row: OperationalResourceWindow) -> dict[str, object]:
    return {
        "id": row.pk,
        "resource_id": row.resource_id,
        "quantity": row.quantity,
        "starts_at": row.required_interval.lower,
        "ends_at": row.required_interval.upper,
        "window_revision": row.window_revision,
        "source_kind": row.source_kind,
        "source_version": row.source_version,
        "schedule_allocation_id": row.schedule_allocation_id,
        "schedule_event_id": row.schedule_event_id,
        "schedule_reservation_revision": row.schedule_reservation_revision,
        "schedule_source_revision": row.schedule_source_revision,
        "predecessor_id": row.predecessor_id,
    }


def evidence_representation(row: OperationalEvidence) -> dict[str, object]:
    return {
        "id": row.pk,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "document_file_id": row.document_file_id,
        "linked_by_membership_id": row.linked_by_membership_id,
        "created_at": row.created_at,
    }


def close_representation(row: PostEventClose) -> dict[str, object]:
    return {
        "id": row.pk,
        "closed_at": row.closed_at,
        "closed_by_membership_id": row.closed_by_membership_id,
        "preparation_revision": row.preparation_revision,
        "source_sha256": row.source_sha256,
    }


def requirement_representation(
    row: resources_port.OperationalRequirementProjection,
) -> dict[str, object]:
    return {
        "id": row.id,
        "resource_id": row.resource_id,
        "resource_name": row.resource_name,
        "resource_nature": row.resource_nature,
        "status": row.status,
        "quantity": row.quantity,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "temporal_source": row.temporal_source,
        "operational_window_id": row.operational_window_id,
        "supplier_names": row.supplier_names,
        "assignments": [
            {
                "id": item.id,
                "status": item.status,
                "quantity": item.quantity,
                "starts_at": item.starts_at,
                "ends_at": item.ends_at,
            }
            for item in row.assignments
        ],
    }


def advanced_event_detail(
    actor: User, organization_reference: UUID | str, *, reservation_id: UUID
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_INCIDENT_READ
    ) as authorization:
        preparation = _get_advanced_preparation(authorization, reservation_id)
        try:
            snapshot = OperationalPlanSnapshot.objects.get(preparation=preparation)
        except OperationalPlanSnapshot.DoesNotExist:
            raise unavailable(
                "El snapshot P13; la preparación requiere incorporación expresa"
            ) from None
        phase_facts = tuple(
            OperationalPhaseFact.objects.filter(preparation=preparation).order_by(
                "created_at", "id"
            )
        )
        setup_start = _effective_phase_fact(
            preparation, OperationalPhaseFact.Phase.SETUP, OperationalPhaseFact.FactKind.STARTED
        )
        setup_end = _effective_phase_fact(
            preparation, OperationalPhaseFact.Phase.SETUP, OperationalPhaseFact.FactKind.COMPLETED
        )
        teardown_start = _effective_phase_fact(
            preparation, OperationalPhaseFact.Phase.TEARDOWN, OperationalPhaseFact.FactKind.STARTED
        )
        teardown_end = _effective_phase_fact(
            preparation,
            OperationalPhaseFact.Phase.TEARDOWN,
            OperationalPhaseFact.FactKind.COMPLETED,
        )
        resources = resources_port.operational_resource_state(authorization, reservation_id)
        evidence = tuple(
            OperationalEvidence.objects.filter(preparation=preparation).order_by("created_at", "id")
        )
        close = PostEventClose.objects.filter(preparation=preparation).first()
        verifications = tuple(OperationalVerification.objects.filter(preparation=preparation))
        incidents = tuple(
            OperationalIncident.objects.filter(preparation=preparation).order_by(
                "reported_at", "id"
            )
        )
        incident_counts_by_type: dict[str, int] = {}
        incident_counts_by_severity: dict[str, int] = {}
        resolution_seconds: list[int] = []
        for incident in incidents:
            incident_counts_by_type[incident.incident_type] = (
                incident_counts_by_type.get(incident.incident_type, 0) + 1
            )
            incident_counts_by_severity[incident.severity] = (
                incident_counts_by_severity.get(incident.severity, 0) + 1
            )
            resolved = (
                incident.events.filter(kind=OperationalIncidentEvent.Kind.RESOLVED)
                .order_by("incident_revision")
                .first()
            )
            if resolved is not None:
                resolution_seconds.append(
                    int((resolved.occurred_at - incident.reported_at).total_seconds())
                )
        required_verifications = [row for row in verifications if row.is_required]
        return {
            "snapshot": {
                "id": snapshot.pk,
                "source_kind": snapshot.source_kind,
                "source_version": snapshot.source_version,
                "event_type_id": snapshot.event_type_id,
                "event_type_label": snapshot.event_type_label,
                "content_sha256": snapshot.content_sha256,
                "roles": snapshot.canonical_payload.get("roles", []),
            },
            "verifications": [verification_representation(row) for row in verifications],
            "phase_facts": [phase_fact_representation(row) for row in phase_facts],
            "responsibilities": [
                responsibility_representation(row)
                for row in OperationalResponsibility.objects.filter(
                    preparation=preparation, superseded_by__isnull=True
                ).order_by("role_key", "phase", "created_at")
            ],
            "incidents": [incident_representation(row) for row in incidents],
            "changes": [
                change_representation(row)
                for row in OperationalChangeProposal.objects.filter(preparation=preparation)
                .select_related("decision")
                .order_by("created_at", "id")
            ],
            "resource_windows": [
                window_representation(row)
                for row in OperationalResourceWindow.objects.filter(
                    preparation=preparation, successor__isnull=True
                ).order_by("required_interval", "id")
            ],
            "resources": [requirement_representation(row) for row in resources],
            "evidence": [evidence_representation(row) for row in evidence],
            "close": None if close is None else close_representation(close),
            "metrics": {
                "readiness_seconds": None
                if preparation.ready_at is None
                else int((preparation.ready_at - preparation.created_at).total_seconds()),
                "setup_seconds": None
                if setup_start is None or setup_end is None
                else int((setup_end.observed_at - setup_start.observed_at).total_seconds()),
                "execution_seconds": None
                if preparation.started_at is None or preparation.completed_at is None
                else int((preparation.completed_at - preparation.started_at).total_seconds()),
                "teardown_seconds": None
                if teardown_start is None or teardown_end is None
                else int((teardown_end.observed_at - teardown_start.observed_at).total_seconds()),
                "verification_required_total": len(required_verifications),
                "verification_required_resolved": sum(
                    row.status != OperationalVerification.Status.PENDING
                    for row in required_verifications
                ),
                "incident_count": len(incidents),
                "incident_counts_by_type": incident_counts_by_type,
                "incident_counts_by_severity": incident_counts_by_severity,
                "incident_resolution_seconds_average": None
                if not resolution_seconds
                else sum(resolution_seconds) // len(resolution_seconds),
                "authorized_change_count": OperationalChangeDecision.objects.filter(
                    proposal__preparation=preparation, approved=True
                ).count(),
                "close_cycle_seconds": None
                if close is None or preparation.completed_at is None
                else int((close.closed_at - preparation.completed_at).total_seconds()),
                "resource_shortage_count": sum(row.status == "shortage" for row in resources),
                "resource_pending_custody_count": sum(
                    item.status in {"reserved", "custody"}
                    for row in resources
                    for item in row.assignments
                ),
            },
        }
