from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from claridez.organizations.tenant_scope import TenantAuthorization

from .assets import render_assets_manifest
from .errors import conflict
from .models import DocumentTemplate, DocumentTemplateVersion, TemplateEvent
from .variables import sanitize_template_html, template_source_hash, validate_variable_schema


@transaction.atomic
def create_template(
    authorization: TenantAuthorization,
    *,
    name: str,
    title: str,
    body_html: str,
    variable_schema: dict[str, Any],
) -> tuple[DocumentTemplate, DocumentTemplateVersion]:
    normalized_name = " ".join(name.split())
    normalized_title = " ".join(title.split())
    sanitized = sanitize_template_html(body_html)
    validate_variable_schema(variable_schema, sanitized)
    source_sha, assets_sha = template_source_hash(
        body_html=sanitized,
        schema=variable_schema,
        assets_manifest=render_assets_manifest(),
    )
    template = DocumentTemplate.objects.create(
        organization_id=authorization.organization_id, name=normalized_name
    )
    version = DocumentTemplateVersion.objects.create(
        organization_id=authorization.organization_id,
        template=template,
        version=1,
        title=normalized_title,
        body_html=sanitized,
        variable_schema=variable_schema,
        source_sha256=source_sha,
        assets_manifest=render_assets_manifest(),
        assets_sha256=assets_sha,
    )
    return template, version


@transaction.atomic
def create_draft_version(
    authorization: TenantAuthorization,
    *,
    template_id: UUID,
    title: str,
    body_html: str,
    variable_schema: dict[str, Any],
) -> DocumentTemplateVersion:
    template = DocumentTemplate.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=template_id
    )
    if template.versions.filter(status=DocumentTemplateVersion.Status.DRAFT).exists():
        raise conflict("draft_exists", "La plantilla ya tiene un borrador.")
    sanitized = sanitize_template_html(body_html)
    validate_variable_schema(variable_schema, sanitized)
    source_sha, assets_sha = template_source_hash(
        body_html=sanitized,
        schema=variable_schema,
        assets_manifest=render_assets_manifest(),
    )
    next_version = (template.versions.aggregate(value=Max("version"))["value"] or 0) + 1
    return DocumentTemplateVersion.objects.create(
        organization_id=authorization.organization_id,
        template=template,
        version=next_version,
        title=" ".join(title.split()),
        body_html=sanitized,
        variable_schema=variable_schema,
        source_sha256=source_sha,
        assets_manifest=render_assets_manifest(),
        assets_sha256=assets_sha,
    )


@transaction.atomic
def update_draft(
    authorization: TenantAuthorization,
    *,
    version_id: UUID,
    title: str,
    body_html: str,
    variable_schema: dict[str, Any],
) -> DocumentTemplateVersion:
    version = DocumentTemplateVersion.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=version_id
    )
    if version.status != DocumentTemplateVersion.Status.DRAFT:
        raise conflict("immutable_template_version", "Solo un borrador puede modificarse.")
    sanitized = sanitize_template_html(body_html)
    validate_variable_schema(variable_schema, sanitized)
    source_sha, assets_sha = template_source_hash(
        body_html=sanitized, schema=variable_schema, assets_manifest=version.assets_manifest
    )
    version.title = " ".join(title.split())
    version.body_html = sanitized
    version.variable_schema = variable_schema
    version.source_sha256 = source_sha
    version.assets_sha256 = assets_sha
    version.save(
        update_fields=[
            "title",
            "body_html",
            "variable_schema",
            "source_sha256",
            "assets_sha256",
            "updated_at",
        ]
    )
    return version


@transaction.atomic
def publish_version(
    authorization: TenantAuthorization, version_id: UUID
) -> DocumentTemplateVersion:
    version = (
        DocumentTemplateVersion.objects.select_for_update()
        .select_related("template")
        .get(organization_id=authorization.organization_id, pk=version_id)
    )
    if version.status != DocumentTemplateVersion.Status.DRAFT:
        raise conflict("invalid_template_state", "Solo un borrador puede publicarse.")
    sanitized = sanitize_template_html(version.body_html)
    validate_variable_schema(version.variable_schema, sanitized)
    source_sha, assets_sha = template_source_hash(
        body_html=sanitized,
        schema=version.variable_schema,
        assets_manifest=version.assets_manifest,
    )
    if source_sha != version.source_sha256 or assets_sha != version.assets_sha256:
        raise conflict("template_integrity_failed", "La plantilla no supera integridad.")
    now = timezone.now()
    version.status = DocumentTemplateVersion.Status.PUBLISHED
    version.published_at = now
    version.published_by_membership_id = authorization.membership_id
    version.save(update_fields=["status", "published_at", "published_by_membership", "updated_at"])
    TemplateEvent.objects.create(
        organization_id=authorization.organization_id,
        template=version.template,
        template_version=version,
        kind=TemplateEvent.Kind.PUBLISHED,
        actor_membership_id=authorization.membership_id,
        occurred_at=now,
    )
    return version


@transaction.atomic
def inactivate_version(
    authorization: TenantAuthorization, version_id: UUID
) -> DocumentTemplateVersion:
    version = (
        DocumentTemplateVersion.objects.select_for_update()
        .select_related("template")
        .get(organization_id=authorization.organization_id, pk=version_id)
    )
    if version.status != DocumentTemplateVersion.Status.PUBLISHED:
        raise conflict("invalid_template_state", "Solo una versión publicada puede inactivarse.")
    version.status = DocumentTemplateVersion.Status.INACTIVE
    version.save(update_fields=["status", "updated_at"])
    TemplateEvent.objects.create(
        organization_id=authorization.organization_id,
        template=version.template,
        template_version=version,
        kind=TemplateEvent.Kind.INACTIVATED,
        actor_membership_id=authorization.membership_id,
        occurred_at=timezone.now(),
    )
    return version


@transaction.atomic
def set_template_active(
    authorization: TenantAuthorization, template_id: UUID, *, active: bool
) -> DocumentTemplate:
    template = DocumentTemplate.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=template_id
    )
    if template.is_active == active:
        return template
    template.is_active = active
    template.revision += 1
    template.save(update_fields=["is_active", "revision", "updated_at"])
    TemplateEvent.objects.create(
        organization_id=authorization.organization_id,
        template=template,
        kind=TemplateEvent.Kind.REACTIVATED if active else TemplateEvent.Kind.INACTIVATED,
        actor_membership_id=authorization.membership_id,
        occurred_at=timezone.now(),
    )
    return template
