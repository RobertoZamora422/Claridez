from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID

from django.utils import timezone

from .errors import DocumentsError
from .models import (
    ArtifactIntegrityEvent,
    ExternalFile,
    ExternalFileEvent,
    GeneratedArtifact,
)
from .storage import private_storage


class StoredEvidence(Protocol):
    organization_id: UUID
    storage_key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class IntegrityVerification:
    content: bytes | None
    result: str

    @property
    def verified(self) -> bool:
        return self.content is not None


def _read_and_hash(row: StoredEvidence) -> tuple[bytes | None, str, int | None, str]:
    try:
        with private_storage().open(row.storage_key) as stream:
            content = _read_all(stream)
    except DocumentsError as error:
        return None, "", None, error.code
    except Exception as error:  # pragma: no cover - provider failures vary by adapter
        return None, "", None, f"storage_error:{type(error).__name__}"
    observed = hashlib.sha256(content).hexdigest()
    if observed != row.sha256 or len(content) != row.size_bytes:
        return None, observed, len(content), "integrity_mismatch"
    return content, observed, len(content), "verified"


def _read_all(stream: BinaryIO) -> bytes:
    chunks: list[bytes] = []
    while chunk := stream.read(1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def verify_generated_artifact(artifact: GeneratedArtifact) -> IntegrityVerification:
    content, observed, size, result = _read_and_hash(artifact)
    now = timezone.now()
    event_result = {
        "verified": ArtifactIntegrityEvent.Result.VERIFIED,
        "integrity_mismatch": ArtifactIntegrityEvent.Result.MISMATCH,
        "object_missing": ArtifactIntegrityEvent.Result.MISSING,
    }.get(result, ArtifactIntegrityEvent.Result.ERROR)
    ArtifactIntegrityEvent.objects.create(
        organization_id=artifact.organization_id,
        artifact=artifact,
        result=event_result,
        expected_sha256=artifact.sha256,
        observed_sha256=observed,
        observed_size_bytes=size,
        detail="" if result == "verified" else result[:500],
        occurred_at=now,
    )
    if content is None:
        artifact.state = GeneratedArtifact.State.INTEGRITY_FAILED
        artifact.save(update_fields=["state"])
    else:
        artifact.verified_at = now
        artifact.save(update_fields=["verified_at"])
    return IntegrityVerification(content, result)


def verify_external_file(row: ExternalFile) -> IntegrityVerification:
    content, _observed, _size, result = _read_and_hash(row)
    if content is None:
        previous = row.state
        row.state = ExternalFile.State.INTEGRITY_FAILED
        row.validation_detail = result[:500]
        row.save(update_fields=["state", "validation_detail", "updated_at"])
        ExternalFileEvent.objects.create(
            organization_id=row.organization_id,
            external_file=row,
            from_state=previous,
            to_state=row.state,
            reason="delivery_integrity_failed",
            detail=result[:500],
            occurred_at=timezone.now(),
        )
    return IntegrityVerification(content, result)
