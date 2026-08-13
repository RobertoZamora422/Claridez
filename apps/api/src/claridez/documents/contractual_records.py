from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max

from claridez.organizations.tenant_scope import TenantAuthorization
from claridez.scheduling.public import contractual_schedule

from .config import document_settings
from .errors import conflict
from .jobs import enqueue_job
from .models import (
    ContractualInstrument,
    ContractualRecord,
    DocumentJob,
    DocumentTemplateVersion,
    IssuedInstrumentVersion,
)
from .snapshots import SCHEMA_VERSION, build_contractual_snapshot
from .variables import resolve_template, validate_variable_schema


def get_or_create_record(
    authorization: TenantAuthorization, *, root_reservation_id: UUID
) -> tuple[ContractualRecord, bool]:
    schedule = contractual_schedule(authorization, root_reservation_id)
    if schedule.root_reservation_id != root_reservation_id:
        raise conflict("not_reservation_root", "La reserva indicada no es una raíz.")
    try:
        with transaction.atomic():
            return ContractualRecord.objects.get_or_create(
                organization_id=authorization.organization_id,
                root_reservation_id=root_reservation_id,
                defaults={"created_by_membership_id": authorization.membership_id},
            )
    except IntegrityError:
        return (
            ContractualRecord.objects.get(
                organization_id=authorization.organization_id,
                root_reservation_id=root_reservation_id,
            ),
            False,
        )


@transaction.atomic
def create_instrument(
    authorization: TenantAuthorization,
    *,
    record_id: UUID,
    instrument_type: str,
    title: str,
) -> ContractualInstrument:
    record = ContractualRecord.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=record_id
    )
    return ContractualInstrument.objects.create(
        organization_id=authorization.organization_id,
        record=record,
        instrument_type=ContractualInstrument.Type(instrument_type),
        title=" ".join(title.split()),
        created_by_membership_id=authorization.membership_id,
    )


@transaction.atomic
def preview(
    authorization: TenantAuthorization,
    *,
    root_reservation_id: UUID,
    template_version_id: UUID,
) -> dict[str, object]:
    template = DocumentTemplateVersion.objects.get(
        organization_id=authorization.organization_id, pk=template_version_id
    )
    if template.status not in {
        DocumentTemplateVersion.Status.DRAFT,
        DocumentTemplateVersion.Status.PUBLISHED,
    }:
        raise conflict("inactive_template", "La versión de plantilla no está disponible.")
    _, snapshot_hash, values, _ = build_contractual_snapshot(
        authorization, root_reservation_id=root_reservation_id
    )
    declarations = validate_variable_schema(template.variable_schema, template.body_html)
    rendered, resolved = resolve_template(
        body_html=template.body_html, declarations=declarations, values=values
    )
    return {
        "kind": "preview",
        "contractual": False,
        "acceptance_allowed": False,
        "watermark": "VISTA PREVIA — NO CONTRACTUAL",
        "snapshot_sha256": snapshot_hash,
        "template_version_id": str(template.pk),
        "resolved_variables": resolved,
        "html": f'<div class="preview-watermark">VISTA PREVIA — NO CONTRACTUAL</div>{rendered}',
    }


@transaction.atomic
def issue_version(
    authorization: TenantAuthorization,
    *,
    instrument_id: UUID,
    template_version_id: UUID,
    idempotency_key: UUID,
    correlation_id: str,
) -> IssuedInstrumentVersion:
    instrument = (
        ContractualInstrument.objects.select_for_update()
        .select_related("record")
        .get(organization_id=authorization.organization_id, pk=instrument_id)
    )
    existing = IssuedInstrumentVersion.objects.filter(
        organization_id=authorization.organization_id, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        if existing.instrument_id != instrument_id:
            raise conflict("idempotency_conflict", "La clave de idempotencia ya fue utilizada.")
        return existing
    template = DocumentTemplateVersion.objects.select_related("template").get(
        organization_id=authorization.organization_id, pk=template_version_id
    )
    if (
        template.status != DocumentTemplateVersion.Status.PUBLISHED
        or not template.template.is_active
    ):
        raise conflict(
            "template_not_published", "La emisión requiere una plantilla publicada activa."
        )
    snapshot, snapshot_hash, values, provenance = build_contractual_snapshot(
        authorization, root_reservation_id=instrument.record.root_reservation_id
    )
    declarations = validate_variable_schema(template.variable_schema, template.body_html)
    rendered, resolved = resolve_template(
        body_html=template.body_html, declarations=declarations, values=values
    )
    next_version = (
        IssuedInstrumentVersion.objects.filter(instrument=instrument).aggregate(
            value=Max("version")
        )["value"]
        or 0
    ) + 1
    config = document_settings()
    row = IssuedInstrumentVersion.objects.create(
        organization_id=authorization.organization_id,
        instrument=instrument,
        version=next_version,
        current_reservation_id=snapshot["sources"]["current_reservation"],
        quotation_version_id=snapshot["sources"]["quotation_version"],
        template_version=template,
        snapshot=snapshot,
        snapshot_schema_version=SCHEMA_VERSION,
        snapshot_sha256=snapshot_hash,
        resolved_variables={**resolved, "rendered_html": rendered},
        provenance=provenance,
        materiality_policy_version="explicit-review-v1",
        renderer_name="WeasyPrint",
        renderer_version="69.0",
        render_environment=config.renderer_required_environment,
        assets_sha256=template.assets_sha256,
        idempotency_key=idempotency_key,
        issued_by_membership_id=authorization.membership_id,
    )
    enqueue_job(
        organization_id=authorization.organization_id,
        job_type=DocumentJob.Type.RENDER_ISSUED_VERSION,
        target_id=row.pk,
        idempotency_key=f"render:{row.pk}",
        correlation_id=correlation_id,
    )
    return row
