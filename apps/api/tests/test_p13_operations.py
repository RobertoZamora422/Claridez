from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, TypedDict, cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client
from django.utils import timezone

from claridez.application.resources_scheduling import reschedule_with_resources
from claridez.catalog.services import create_event_type
from claridez.documents.domain_assets import PrivateFileProjection
from claridez.documents.models import PrivateDomainFile
from claridez.operations.advanced import (
    advanced_event_detail,
    attach_operational_evidence,
    close_post_event,
    correct_phase_fact,
    create_template_version,
    decide_change,
    open_incident,
    propose_change,
    publish_template_version,
    record_phase_fact,
    reserve_operational_window,
    transition_incident,
    update_verification,
)
from claridez.operations.advanced_models import (
    OperationalChangeProposal,
    OperationalEvidence,
    OperationalIncident,
    OperationalPhaseFact,
    OperationalPlanSnapshot,
    OperationalResourceWindow,
    OperationalVerification,
    ReadinessDeviation,
)
from claridez.operations.errors import OperationsError
from claridez.operations.models import EventPreparation, PreparationItem
from claridez.operations.services import (
    assign_preparation,
    complete_event,
    mark_ready,
    read_event,
    start_event,
    update_item,
)
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.resources.errors import ResourcesError
from claridez.resources.models import (
    Resource,
    ResourceAssignment,
    ResourceCapacityAllocation,
    ResourceRequirement,
    UnitDefinition,
)
from claridez.resources.services import (
    create_requirement,
    create_resource,
    create_unit,
    execute_assignment,
    reserve_resource,
)
from claridez.scheduling.models import Reservation, ScheduleAllocation
from claridez.scheduling.services import cancel_reservation as cancel_scheduled_reservation
from tests.test_operations import PASSWORD, _confirmed, _user

P13_CAPABILITIES = {
    Capability.OPERATION_TEMPLATE_READ,
    Capability.OPERATION_TEMPLATE_MANAGE,
    Capability.OPERATION_INCIDENT_READ,
    Capability.OPERATION_INCIDENT_MANAGE,
    Capability.OPERATION_CHANGE_AUTHORIZE,
    Capability.OPERATION_EVIDENCE_READ,
    Capability.OPERATION_EVIDENCE_MANAGE,
    Capability.OPERATION_CLOSE,
}


class _RescheduleValues(TypedDict):
    reservation_id: UUID
    revision: int
    space_id: UUID
    starts_at_local: datetime
    ends_at_local: datetime
    timezone_name: str
    reason: str
    commercial_terms_unchanged: bool


def test_operations_p13_consumes_domain_authorities_through_public_ports() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "claridez" / "operations"
    violations: list[str] = []
    for module in package.rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports = [node.module]
            for imported in imports:
                if imported.startswith("claridez.commercial") and imported != (
                    "claridez.commercial.public"
                ):
                    violations.append(f"{module.relative_to(package)}: {imported}")
                if (
                    module.name in {"advanced.py", "advanced_models.py"}
                    and imported.startswith(
                        (
                            "claridez.catalog",
                            "claridez.documents",
                            "claridez.resources",
                            "claridez.scheduling",
                        )
                    )
                    and not imported.endswith(".public")
                ):
                    violations.append(f"{module.relative_to(package)}: {imported}")
    assert violations == []


def _organization(name: str, email: str) -> tuple[Any, Any]:
    owner = _user(email)
    return owner, create_organization(owner_user_id=owner.pk, name=name)


def _template(owner: Any, organization_id: UUID) -> dict[str, object]:
    event_type = create_event_type(owner, organization_id, name="Boda")
    created = create_template_version(
        owner,
        organization_id,
        event_type_id=event_type["id"],
        name="Plan boda",
        definitions={
            "readiness": [
                {
                    "key": "briefing_operativo",
                    "title": "Briefing operativo validado",
                    "section": "definitions",
                    "is_required": True,
                    "days_before": 1,
                }
            ],
            "verifications": [
                {
                    "key": "setup_real",
                    "phase": "setup",
                    "title": "Montaje real verificado",
                    "is_required": True,
                },
                {
                    "key": "execution_real",
                    "phase": "execution",
                    "title": "Ejecución verificada",
                    "is_required": True,
                },
                {
                    "key": "teardown_real",
                    "phase": "teardown",
                    "title": "Desmontaje verificado",
                    "is_required": True,
                },
                {
                    "key": "post_real",
                    "phase": "post_event",
                    "title": "Cierre documental verificado",
                    "is_required": True,
                },
            ],
            "roles": [],
            "resource_needs": [],
        },
        idempotency_key=uuid4(),
    )
    return publish_template_version(
        owner,
        organization_id,
        version_id=UUID(str(created["id"])),
        idempotency_key=uuid4(),
    )


def _service_resource(owner: Any, organization_id: UUID, *, name: str) -> Resource:
    unit = create_unit(
        owner,
        organization_id,
        code=f"unit-{uuid4().hex[:8]}",
        name="Unidad",
        symbol="u",
        dimension=UnitDefinition.Dimension.COUNT,
        idempotency_key=uuid4(),
    )
    return create_resource(
        owner,
        organization_id,
        name=name,
        nature=Resource.Nature.SUPPLIED_SERVICE,
        base_unit_id=unit.pk,
        declared_capacity=Decimal("5"),
        idempotency_key=uuid4(),
    )


def _resource_template(owner: Any, organization_id: UUID, resource_id: UUID) -> dict[str, object]:
    event_type = create_event_type(owner, organization_id, name="Boda")
    created = create_template_version(
        owner,
        organization_id,
        event_type_id=event_type["id"],
        name="Plan con recursos",
        definitions={
            "readiness": [],
            "verifications": [],
            "roles": [],
            "resource_needs": [
                {
                    "key": "servicio_evento",
                    "resource_id": str(resource_id),
                    "quantity": "1",
                    "start_anchor": "event_start",
                    "start_offset_minutes": 0,
                    "end_anchor": "event_end",
                    "end_offset_minutes": 0,
                }
            ],
        },
        idempotency_key=uuid4(),
    )
    return publish_template_version(
        owner,
        organization_id,
        version_id=UUID(str(created["id"])),
        idempotency_key=uuid4(),
    )


def _assign_and_resolve_readiness(owner: Any, creation: Any, reservation_id: UUID) -> int:
    detail = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    assigned = assign_preparation(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=detail["preparation"]["revision"],
        responsible_membership_id=creation.owner_membership.pk,
    )
    revision = int(assigned["preparation"]["revision"])
    for item in assigned["preparation"]["items"]:
        changed = update_item(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            item_id=item["id"],
            revision=item["revision"],
            values={"status": "completed"},
        )
        revision = int(changed["preparation_revision"])
    return revision


def _verification(detail: Any, phase: str) -> dict[str, Any]:
    return next(
        item
        for item in cast(list[dict[str, Any]], detail["verifications"])
        if item["phase"] == phase
    )


def _resolve_verification(
    owner: Any, organization_id: UUID, reservation_id: UUID, phase: str
) -> dict[str, object]:
    detail = advanced_event_detail(owner, organization_id, reservation_id=reservation_id)
    item = _verification(detail, phase)
    return update_verification(
        owner,
        organization_id,
        reservation_id=reservation_id,
        verification_id=UUID(str(item["id"])),
        revision=int(item["revision"]),
        status="completed",
        reason="",
        idempotency_key=uuid4(),
    )


@pytest.mark.django_db
def test_p13_fallback_is_explicit_and_does_not_reinterpret_baseline_5_2() -> None:
    owner, creation = _organization("P13 fallback", "p13-fallback@example.com")
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))

    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation = EventPreparation.objects.get(pk=reservation_id)
        snapshot = OperationalPlanSnapshot.objects.get(preparation=preparation)
        items = tuple(PreparationItem.objects.filter(preparation=preparation))

    assert snapshot.source_kind == OperationalPlanSnapshot.SourceKind.SYSTEM
    assert snapshot.source_version == "operations-p13-system-v1"
    assert len(items) == 7
    assert {item.source_kind for item in items} == {PreparationItem.SourceKind.BASELINE_5_2}
    assert {item.baseline_key for item in items} == {
        "space_layout",
        "guest_count",
        "special_requirements",
        "entry_schedule",
        "furniture",
        "decoration",
        "final_readiness_review",
    }
    fallback_metrics = cast(
        dict[str, Any],
        advanced_event_detail(owner, creation.organization.pk, reservation_id=reservation_id)[
            "metrics"
        ],
    )
    assert fallback_metrics["setup_seconds"] is None


@pytest.mark.django_db
def test_readiness_is_independent_from_execution_teardown_and_post_event() -> None:
    owner, creation = _organization("P13 lifecycle", "p13-lifecycle@example.com")
    _template(owner, creation.organization.pk)
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))

    detail = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    assert len(detail["preparation"]["items"]) == 8
    assert (
        sum(
            item["source_kind"] == "p13_template_readiness"
            for item in detail["preparation"]["items"]
        )
        == 1
    )
    revision = _assign_and_resolve_readiness(owner, creation, reservation_id)
    ready = mark_ready(
        owner, creation.organization.pk, reservation_id=reservation_id, revision=revision
    )
    assert ready["preparation"]["status"] == "ready"
    advanced = cast(
        dict[str, Any],
        advanced_event_detail(owner, creation.organization.pk, reservation_id=reservation_id),
    )
    assert {item["phase"] for item in advanced["verifications"] if item["status"] == "pending"} == {
        "setup",
        "execution",
        "teardown",
        "post_event",
    }

    with pytest.raises(OperationsError, match="verificaciones"):
        start_event(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            revision=ready["preparation"]["revision"],
        )
    _resolve_verification(owner, creation.organization.pk, reservation_id, "setup")
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation = EventPreparation.objects.get(pk=reservation_id)
    setup_start = timezone.now() - timedelta(hours=2)
    started_fact = record_phase_fact(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        phase="setup",
        fact_kind="started",
        revision=preparation.revision,
        observed_at=setup_start,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    with pytest.raises(OperationsError, match="finalizada"):
        start_event(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            revision=preparation.revision,
        )
    record_phase_fact(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        phase="setup",
        fact_kind="completed",
        revision=preparation.revision,
        observed_at=setup_start + timedelta(minutes=45),
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    running = start_event(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=preparation.revision,
    )
    with pytest.raises(OperationsError, match="verificaciones"):
        complete_event(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            revision=running["preparation"]["revision"],
        )
    _resolve_verification(owner, creation.organization.pk, reservation_id, "execution")
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    completed = complete_event(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=preparation.revision,
    )
    assert completed["preparation"]["status"] == "completed"
    with pytest.raises(OperationsError, match="postevento"):
        close_post_event(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            revision=completed["preparation"]["revision"],
            idempotency_key=uuid4(),
        )
    _resolve_verification(owner, creation.organization.pk, reservation_id, "teardown")
    _resolve_verification(owner, creation.organization.pk, reservation_id, "post_event")
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    teardown_start = timezone.now()
    record_phase_fact(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        phase="teardown",
        fact_kind="started",
        revision=preparation.revision,
        observed_at=teardown_start,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    record_phase_fact(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        phase="teardown",
        fact_kind="completed",
        revision=preparation.revision,
        observed_at=teardown_start + timedelta(minutes=30),
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    closed = close_post_event(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=preparation.revision,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation.refresh_from_db()
    metrics = cast(
        dict[str, Any],
        advanced_event_detail(owner, creation.organization.pk, reservation_id=reservation_id)[
            "metrics"
        ],
    )
    assert preparation.status == EventPreparation.Status.COMPLETED
    assert closed["id"]
    assert metrics["setup_seconds"] == 45 * 60
    assert metrics["teardown_seconds"] == 30 * 60
    assert metrics["execution_seconds"] is not None
    assert started_fact["provenance"] == "user_observation"


@pytest.mark.django_db(transaction=True)
def test_template_readiness_requires_authorized_append_only_deviation_and_db_guardians() -> None:
    owner, creation = _organization("P13 readiness", "p13-readiness@example.com")
    _template(owner, creation.organization.pk)
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        item = PreparationItem.objects.get(
            preparation_id=reservation_id,
            source_kind=PreparationItem.SourceKind.P13_TEMPLATE_READINESS,
        )

    with pytest.raises(OperationsError) as service_error:
        update_item(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            item_id=item.pk,
            revision=item.revision,
            values={"title": "Desvío silencioso"},
        )
    assert service_error.value.code == "authorized_change_required"
    with (
        authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ),
        pytest.raises((DatabaseError, IntegrityError)),
        transaction.atomic(),
    ):
        PreparationItem.objects.filter(pk=item.pk).update(title="Desvío bulk")
        connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")
    with (
        authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ),
        pytest.raises((DatabaseError, IntegrityError)),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE operations_preparationitem SET title = %s WHERE id = %s",
            ["Desvío SQL", item.pk],
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation = EventPreparation.objects.get(pk=reservation_id)
    proposal = propose_change(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        scope=OperationalChangeProposal.Scope.READINESS,
        target_id=item.pk,
        proposed_payload={"title": "Briefing autorizado"},
        reason="Ajuste específico del evento",
        impact="Cambia solo la proyección efectiva del evento",
        revision=preparation.revision,
        idempotency_key=uuid4(),
    )
    decision = decide_change(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        proposal_id=UUID(str(proposal["id"])),
        approved=True,
        reason="Cambio autorizado",
        revision=preparation.revision,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        item.refresh_from_db()
        deviation = ReadinessDeviation.objects.get(item=item)
        definition = item.template_readiness_definition
        assert definition is not None
        definition_title = definition.title
    assert decision["status"] == "approved"
    assert item.title == "Briefing autorizado"
    assert deviation.before_payload["title"] == "Briefing operativo validado"
    assert deviation.effective_payload["title"] == "Briefing autorizado"
    assert definition_title == "Briefing operativo validado"


@pytest.mark.django_db(transaction=True)
def test_setup_teardown_facts_are_append_only_correctable_and_guard_impossible_sql() -> None:
    owner, creation = _organization("P13 phases", "p13-phases@example.com")
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))
    revision = _assign_and_resolve_readiness(owner, creation, reservation_id)
    ready = mark_ready(
        owner, creation.organization.pk, reservation_id=reservation_id, revision=revision
    )
    observed = timezone.now() - timedelta(hours=1)
    with pytest.raises(OperationsError, match="iniciarse"):
        record_phase_fact(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            phase="setup",
            fact_kind="completed",
            revision=ready["preparation"]["revision"],
            observed_at=observed,
            idempotency_key=uuid4(),
        )
    started = record_phase_fact(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        phase="setup",
        fact_kind="started",
        revision=ready["preparation"]["revision"],
        observed_at=observed,
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation = EventPreparation.objects.get(pk=reservation_id)
    corrected = correct_phase_fact(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        fact_id=UUID(str(started["id"])),
        revision=preparation.revision,
        observed_at=observed - timedelta(minutes=5),
        reason="Reloj de campo corregido",
        idempotency_key=uuid4(),
    )
    assert corrected["corrects_id"] == started["id"]
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        assert OperationalPhaseFact.objects.filter(preparation_id=reservation_id).count() == 2
        original = OperationalPhaseFact.objects.get(pk=UUID(str(started["id"])))
        with pytest.raises((DatabaseError, IntegrityError)), transaction.atomic():
            OperationalPhaseFact.objects.filter(pk=original.pk).update(
                observed_at=observed + timedelta(days=1)
            )
            connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.django_db(transaction=True)
def test_incident_projection_and_authorized_verification_change_are_ledger_guarded() -> None:
    owner, creation = _organization("P13 ledger", "p13-ledger@example.com")
    _template(owner, creation.organization.pk)
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))
    incident = cast(
        dict[str, Any],
        open_incident(
            owner,
            creation.organization.pk,
            reservation_id=reservation_id,
            incident_type=OperationalIncident.Type.SERVICE_QUALITY,
            severity=OperationalIncident.Severity.MEDIUM,
            description="Demora observable",
            impact="Inicio desplazado sin afectar agenda",
            responsible_membership_id=creation.owner_membership.pk,
            idempotency_key=uuid4(),
        ),
    )
    contained = transition_incident(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        incident_id=UUID(str(incident["id"])),
        revision=int(incident["revision"]),
        status=OperationalIncident.Status.CONTAINED,
        detail="Contención aplicada",
        idempotency_key=uuid4(),
    )
    assert contained["status"] == "contained"
    with (
        authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ),
        pytest.raises((DatabaseError, IntegrityError)),
        transaction.atomic(),
    ):
        OperationalIncident.objects.filter(pk=UUID(str(incident["id"]))).update(status="resolved")
        connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")

    detail = advanced_event_detail(owner, creation.organization.pk, reservation_id=reservation_id)
    verification = _verification(detail, "setup")
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation = EventPreparation.objects.get(pk=reservation_id)
    proposal = propose_change(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        scope=OperationalChangeProposal.Scope.VERIFICATION,
        target_id=UUID(str(verification["id"])),
        proposed_payload={"title": "Montaje validado por supervisor"},
        reason="Ajuste operativo del evento",
        impact="Mantiene fase y obligatoriedad",
        revision=preparation.revision,
        idempotency_key=uuid4(),
    )
    decided = decide_change(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        proposal_id=UUID(str(proposal["id"])),
        approved=True,
        reason="Aprobado",
        revision=preparation.revision,
        idempotency_key=uuid4(),
    )
    assert decided["status"] == "approved"
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        changed = OperationalVerification.objects.get(pk=verification["id"])
    assert changed.revision == 2
    assert changed.title == "Montaje validado por supervisor"


@pytest.mark.django_db(transaction=True)
def test_resources_preserve_both_temporal_sources_and_full_scheduling_concordance() -> None:
    owner, creation = _organization("P13 resources", "p13-resources@example.com")
    organization_id = creation.organization.pk
    p13_resource = _service_resource(owner, organization_id, name="Servicio P13")
    legacy_resource = _service_resource(owner, organization_id, name="Servicio legacy")
    _resource_template(owner, organization_id, p13_resource.pk)
    reservation = _confirmed(owner, organization_id)
    reservation_id = UUID(str(reservation["id"]))
    detail = cast(
        dict[str, Any],
        advanced_event_detail(owner, organization_id, reservation_id=reservation_id),
    )
    window_data = detail["resource_windows"][0]

    reserved_window = reserve_operational_window(
        owner,
        organization_id,
        reservation_id=reservation_id,
        window_id=UUID(str(window_data["id"])),
        reason="Necesidad temporal del plan",
        idempotency_key=uuid4(),
    )
    p13_assignment = reserve_resource(
        owner,
        organization_id,
        requirement_id=UUID(str(reserved_window["requirement_id"])),
        source_location_id=None,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )
    legacy_requirement = create_requirement(
        owner,
        organization_id,
        reservation_id=reservation_id,
        resource_id=legacy_resource.pk,
        quantity=Decimal("1"),
        reason="Procedencia P12",
        idempotency_key=uuid4(),
    )
    legacy_assignment = reserve_resource(
        owner,
        organization_id,
        requirement_id=legacy_requirement.pk,
        source_location_id=None,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )

    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        p13_requirement = ResourceRequirement.objects.get(
            pk=UUID(str(reserved_window["requirement_id"]))
        )
        p13_allocation = ResourceCapacityAllocation.objects.get(assignment=p13_assignment)
        legacy_allocation = ResourceCapacityAllocation.objects.get(assignment=legacy_assignment)
        current_reservation = Reservation.objects.get(pk=reservation_id)
        window = OperationalResourceWindow.objects.get(pk=window_data["id"])
        preparation_revision = EventPreparation.objects.get(pk=reservation_id).revision
    assert p13_requirement.temporal_source == ResourceRequirement.TemporalSource.OPERATIONS_WINDOW
    assert p13_requirement.operational_window_id == window.pk
    assert p13_requirement.resource_interval == window.required_interval
    assert p13_assignment.resource_interval == window.required_interval
    assert p13_allocation.resource_interval == window.required_interval
    assert (
        legacy_requirement.temporal_source
        == ResourceRequirement.TemporalSource.SCHEDULING_EVENT_INTERVAL
    )
    assert legacy_requirement.resource_interval == current_reservation.event_interval
    assert legacy_assignment.resource_interval == current_reservation.event_interval
    assert legacy_allocation.resource_interval == current_reservation.event_interval

    with (
        authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ),
        pytest.raises((DatabaseError, IntegrityError)),
        transaction.atomic(),
    ):
        ResourceRequirement.objects.filter(pk=p13_requirement.pk).update(
            temporal_source=ResourceRequirement.TemporalSource.SCHEDULING_EVENT_INTERVAL
        )
    proposal = propose_change(
        owner,
        organization_id,
        reservation_id=reservation_id,
        scope=OperationalChangeProposal.Scope.RESOURCE_WINDOW,
        target_id=window.pk,
        proposed_payload={"start_offset_minutes": -10000},
        reason="Necesidad fuera del espacio",
        impact="Requeriría ampliar la ocupación de Scheduling",
        revision=preparation_revision,
        idempotency_key=uuid4(),
    )
    with pytest.raises(OperationsError) as outside:
        decide_change(
            owner,
            organization_id,
            reservation_id=reservation_id,
            proposal_id=UUID(str(proposal["id"])),
            approved=True,
            reason="No puede autorizarse fuera de agenda",
            revision=preparation_revision,
            idempotency_key=uuid4(),
        )
    assert outside.value.code == "operation_window_outside_occupancy"

    other = _confirmed(owner, organization_id, days=35, phone="0991234568")
    with authorized_tenant_scope(owner, organization_id, Capability.OPERATION_READ):
        foreign_allocation = ScheduleAllocation.objects.select_related("source_event").get(
            reservation_id=other["id"]
        )
        with pytest.raises((DatabaseError, IntegrityError)), transaction.atomic():
            OperationalResourceWindow.objects.create(
                organization_id=organization_id,
                preparation_id=reservation_id,
                snapshot=window.snapshot,
                resource_need=window.resource_need,
                root_reservation_id=window.root_reservation_id,
                reservation_id=reservation_id,
                schedule_allocation=window.schedule_allocation,
                schedule_event=foreign_allocation.source_event,
                resource=window.resource,
                quantity=window.quantity,
                required_interval=window.required_interval,
                window_revision=1,
                source_kind=OperationalResourceWindow.SourceKind.ORGANIZATION_TEMPLATE,
                source_version=window.source_version,
                schedule_reservation_revision=window.schedule_reservation_revision,
                schedule_source_revision=window.schedule_source_revision,
                idempotency_key=uuid4(),
                payload_sha256="0" * 64,
            )

    reschedule_values: _RescheduleValues = {
        "reservation_id": reservation_id,
        "revision": current_reservation.revision,
        "space_id": current_reservation.space_id,
        "starts_at_local": datetime(2026, 10, 8, 18, 0),
        "ends_at_local": datetime(2026, 10, 8, 23, 0),
        "timezone_name": "America/Guayaquil",
        "reason": "Reprogramación operacional",
        "commercial_terms_unchanged": True,
    }
    with pytest.raises(ResourcesError) as transfer_error:
        reschedule_with_resources(
            owner,
            organization_id,
            idempotency_key=uuid4(),
            carry_resource_assignment_ids=(p13_assignment.pk,),
            **reschedule_values,
        )
    assert transfer_error.value.code == "assignment_selection_conflict"
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        current_reservation.refresh_from_db()
        p13_assignment.refresh_from_db()
        assert current_reservation.status == Reservation.Status.CONFIRMED
        assert p13_assignment.status == ResourceAssignment.Status.RESERVED

    result = reschedule_with_resources(
        owner,
        organization_id,
        idempotency_key=uuid4(),
        **reschedule_values,
    )
    successor_id = UUID(str(result["reservation"]["id"]))
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        current_reservation.refresh_from_db()
        p13_assignment.refresh_from_db()
        legacy_assignment.refresh_from_db()
        p13_requirement.refresh_from_db()
        legacy_requirement.refresh_from_db()
        successor = Reservation.objects.get(pk=successor_id)
        successor_preparation = EventPreparation.objects.get(pk=successor_id)
        successor_snapshot = OperationalPlanSnapshot.objects.get(preparation=successor_preparation)
        successor_window = OperationalResourceWindow.objects.get(preparation=successor_preparation)
        assert current_reservation.status == Reservation.Status.RESCHEDULED
        assert p13_assignment.status == ResourceAssignment.Status.RELEASED
        assert legacy_assignment.status == ResourceAssignment.Status.RELEASED
        assert p13_requirement.status == ResourceRequirement.Status.CANCELLED
        assert legacy_requirement.status == ResourceRequirement.Status.CANCELLED
        assert successor_snapshot.source_version == window.snapshot.source_version
        assert successor_window.required_interval != window.required_interval
        assert successor_window.reservation_id == successor.pk
        assert window.required_interval == p13_allocation.resource_interval

    cancel_scheduled_reservation(
        owner,
        organization_id,
        reservation_id=successor_id,
        reason="Cancelación posterior a reprogramación",
    )
    with authorized_tenant_scope(owner, organization_id, Capability.OPERATION_READ):
        successor_preparation.refresh_from_db()
        assert successor_preparation.status == EventPreparation.Status.CANCELLED
        assert (
            OperationalResourceWindow.objects.filter(preparation=successor_preparation).count() == 1
        )


@pytest.mark.django_db(transaction=True)
def test_historical_shortage_requires_clean_documents_evidence_but_not_false_satisfaction() -> None:
    owner, creation = _organization("P13 shortage", "p13-shortage@example.com")
    organization_id = creation.organization.pk
    unit = create_unit(
        owner,
        organization_id,
        code="shortage-unit",
        name="Unidad",
        symbol="u",
        dimension=UnitDefinition.Dimension.COUNT,
        idempotency_key=uuid4(),
    )
    unavailable_resource = create_resource(
        owner,
        organization_id,
        name="Servicio sin capacidad",
        nature=Resource.Nature.SUPPLIED_SERVICE,
        base_unit_id=unit.pk,
        declared_capacity=None,
        idempotency_key=uuid4(),
    )
    reservation = _confirmed(owner, organization_id, phone="0991234570")
    reservation_id = UUID(str(reservation["id"]))
    requirement = create_requirement(
        owner,
        organization_id,
        reservation_id=reservation_id,
        resource_id=unavailable_resource.pk,
        quantity="1",
        reason="Faltante conocido",
        idempotency_key=uuid4(),
    )
    assert requirement.status == ResourceRequirement.Status.SHORTAGE
    revision = _assign_and_resolve_readiness(owner, creation, reservation_id)
    ready = mark_ready(owner, organization_id, reservation_id=reservation_id, revision=revision)
    running = start_event(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=ready["preparation"]["revision"],
    )
    completed = complete_event(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=running["preparation"]["revision"],
    )
    incident = cast(
        dict[str, Any],
        open_incident(
            owner,
            organization_id,
            reservation_id=reservation_id,
            incident_type=OperationalIncident.Type.RESOURCE,
            severity=OperationalIncident.Severity.MEDIUM,
            description="El evento operó con el faltante conocido",
            impact="Se aplicó una alternativa operacional",
            responsible_membership_id=creation.owner_membership.pk,
            idempotency_key=uuid4(),
        ),
    )
    transition_incident(
        owner,
        organization_id,
        reservation_id=reservation_id,
        incident_id=UUID(str(incident["id"])),
        revision=int(incident["revision"]),
        status=OperationalIncident.Status.CONTAINED,
        detail="Consecuencia contenida",
        idempotency_key=uuid4(),
    )
    with pytest.raises(OperationsError) as missing_evidence:
        close_post_event(
            owner,
            organization_id,
            reservation_id=reservation_id,
            revision=int(completed["preparation"]["revision"]),
            idempotency_key=uuid4(),
        )
    assert missing_evidence.value.code == "resources_block_close"

    with authorized_tenant_scope(owner, organization_id, Capability.OPERATION_EVIDENCE_MANAGE):
        document_file = PrivateDomainFile.objects.create(
            organization_id=organization_id,
            owner_domain="operations",
            owner_id=reservation_id,
            purpose="operational_evidence",
            display_name="faltante.txt",
            storage_key=f"test/{uuid4()}",
            declared_media_type="text/plain",
            detected_media_type="text/plain",
            extension=".txt",
            sha256="1" * 64,
            size_bytes=8,
            state=PrivateDomainFile.State.CLEAN,
            uploaded_by_membership_id=creation.owner_membership.pk,
            available_at=timezone.now(),
        )
    projection = PrivateFileProjection(
        id=document_file.pk,
        owner_id=reservation_id,
        purpose="operational_evidence",
        display_name="faltante.txt",
        media_type="text/plain",
        sha256="1" * 64,
        size_bytes=8,
        state="clean",
    )
    with patch(
        "claridez.operations.advanced.documents_port.receive_operational_evidence",
        return_value=projection,
    ) as receive:
        evidence = attach_operational_evidence(
            owner,
            organization_id,
            reservation_id=reservation_id,
            target_kind=OperationalEvidence.TargetKind.INCIDENT,
            target_id=UUID(str(incident["id"])),
            display_name="faltante.txt",
            declared_media_type="text/plain",
            source=BytesIO(b"faltante"),
            correlation_id="p13-shortage",
            idempotency_key=uuid4(),
        )
    receive.assert_called_once()
    closed = close_post_event(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=int(completed["preparation"]["revision"]),
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.RESOURCE_READ):
        requirement.refresh_from_db()
        preparation = EventPreparation.objects.get(pk=reservation_id)
        linked = OperationalEvidence.objects.get(pk=UUID(str(evidence["id"])))
    assert requirement.status == ResourceRequirement.Status.SHORTAGE
    assert preparation.status == EventPreparation.Status.COMPLETED
    assert linked.document_file_id == document_file.pk
    assert closed["id"]


@pytest.mark.django_db
def test_reserved_resource_blocks_post_event_close_until_physical_commitment_is_fulfilled() -> None:
    owner, creation = _organization("P13 custody gate", "p13-custody@example.com")
    organization_id = creation.organization.pk
    resource = _service_resource(owner, organization_id, name="Servicio comprometido")
    reservation = _confirmed(owner, organization_id, phone="0991234571")
    reservation_id = UUID(str(reservation["id"]))
    requirement = create_requirement(
        owner,
        organization_id,
        reservation_id=reservation_id,
        resource_id=resource.pk,
        quantity="1",
        reason="Compromiso físico pendiente",
        idempotency_key=uuid4(),
    )
    assignment = reserve_resource(
        owner,
        organization_id,
        requirement_id=requirement.pk,
        source_location_id=None,
        serialized_asset_id=None,
        idempotency_key=uuid4(),
    )
    revision = _assign_and_resolve_readiness(owner, creation, reservation_id)
    ready = mark_ready(owner, organization_id, reservation_id=reservation_id, revision=revision)
    running = start_event(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=ready["preparation"]["revision"],
    )
    completed = complete_event(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=running["preparation"]["revision"],
    )
    with pytest.raises(OperationsError) as pending:
        close_post_event(
            owner,
            organization_id,
            reservation_id=reservation_id,
            revision=int(completed["preparation"]["revision"]),
            idempotency_key=uuid4(),
        )
    assert pending.value.code == "resources_block_close"
    execute_assignment(
        owner,
        organization_id,
        assignment_id=assignment.pk,
        action="fulfill",
        notes="Servicio cumplido",
        idempotency_key=uuid4(),
    )
    closed = close_post_event(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=int(completed["preparation"]["revision"]),
        idempotency_key=uuid4(),
    )
    assert closed["id"]


@pytest.mark.django_db
def test_p13_http_exposes_advanced_event_and_template_collection() -> None:
    owner, creation = _organization("P13 HTTP", "p13-http@example.com")
    reservation = _confirmed(owner, creation.organization.pk, phone="0991234572")
    client = Client()
    login = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": owner.email, "password": PASSWORD}),
        content_type="application/json",
    )
    assert login.status_code == 200
    base = f"/api/v1/organizations/{creation.organization.pk}/operations"

    advanced = client.get(f"{base}/events/{reservation['id']}/advanced/")
    assert advanced.status_code == 200
    assert advanced.json()["snapshot"]["source_version"] == "operations-p13-system-v1"
    templates = client.get(f"{base}/templates/")
    assert templates.status_code == 200
    assert templates.json() == []


@pytest.mark.django_db
def test_p13_capability_matrix_is_exact_for_five_roles_and_tenants_are_isolated() -> None:
    for role in (
        Membership.Role.OWNER,
        Membership.Role.ADMINISTRATOR,
        Membership.Role.OPERATIONS,
    ):
        assert capabilities_for_role(role) >= P13_CAPABILITIES
    assert not (P13_CAPABILITIES & capabilities_for_role(Membership.Role.COMMERCIAL))
    assert not (P13_CAPABILITIES & capabilities_for_role(Membership.Role.FINANCE))
    assert Capability.OPERATION_READ in capabilities_for_role(Membership.Role.COMMERCIAL)
    assert Capability.OPERATION_READ not in capabilities_for_role(Membership.Role.FINANCE)

    first_owner, first = _organization("P13 tenant first", "p13-first@example.com")
    second_owner, second = _organization("P13 tenant second", "p13-second@example.com")
    reservation = _confirmed(first_owner, first.organization.pk)
    with pytest.raises(OperationsError):
        advanced_event_detail(
            second_owner,
            second.organization.pk,
            reservation_id=UUID(str(reservation["id"])),
        )
