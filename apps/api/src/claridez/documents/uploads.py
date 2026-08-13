from __future__ import annotations

from typing import BinaryIO
from uuid import UUID

from django.db import transaction

from claridez.organizations.tenant_scope import TenantAuthorization

from .config import document_settings
from .external_files import buffered_upload, inspect_upload
from .jobs import enqueue_job
from .models import ContractualRecord, DocumentJob, ExternalFile
from .storage import opaque_object_key, private_storage, stream_sha256


def receive_external_file(
    authorization: TenantAuthorization,
    *,
    record_id: UUID,
    display_name: str,
    declared_media_type: str,
    source: BinaryIO,
    correlation_id: str,
) -> ExternalFile:
    buffered = buffered_upload(source, max_bytes=document_settings().max_upload_bytes)
    validated = inspect_upload(
        display_name=display_name, declared_media_type=declared_media_type, stream=buffered
    )
    size, digest = stream_sha256(buffered)
    key = opaque_object_key("quarantine")
    with transaction.atomic():
        record = ContractualRecord.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=record_id
        )
        row = ExternalFile.objects.create(
            organization_id=authorization.organization_id,
            record=record,
            display_name=validated.display_name,
            storage_key=key,
            declared_media_type=declared_media_type,
            detected_media_type=validated.media_type,
            extension=validated.extension,
            sha256=digest,
            size_bytes=size,
            state=ExternalFile.State.UPLOADING,
            uploaded_by_membership_id=authorization.membership_id,
        )
        enqueue_job(
            organization_id=authorization.organization_id,
            job_type=DocumentJob.Type.FINALIZE_EXTERNAL_UPLOAD,
            target_id=row.pk,
            idempotency_key=f"finalize-upload:{row.pk}",
            correlation_id=correlation_id,
        )
    private_storage().put(
        key=key,
        stream=buffered,
        size_bytes=size,
        sha256=digest,
        media_type=validated.media_type,
    )
    return row
