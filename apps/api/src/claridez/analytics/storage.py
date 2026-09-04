"""Storage privado P15 write-once, independiente del estado y los adaptadores Documents."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

FORMATS = frozenset({"csv", "xlsx", "pdf"})
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


class StorageIntegrityError(Exception):
    """Conflicto terminal: nunca se sobrescribe la identidad ya publicada."""


@dataclass(frozen=True, slots=True)
class PublishedObject:
    object_key: str
    sha256: str
    byte_size: int
    format: str


def object_key(organization_id: UUID, artifact_id: UUID, format: str) -> str:
    if format not in FORMATS:
        raise ValueError("formato de exportación no soportado")
    identity = f"claridez.analytics.artifact@1:{organization_id}:{artifact_id}:{format}"
    opaque = hashlib.sha256(identity.encode("ascii")).hexdigest()
    return f"{opaque[:2]}/{opaque}.{format}"


class AnalyticsStorage(Protocol):
    def publish(
        self,
        organization_id: UUID,
        artifact_id: UUID,
        format: str,
        content: bytes,
    ) -> PublishedObject: ...

    def read(
        self,
        organization_id: UUID,
        artifact_id: UUID,
        metadata: PublishedObject,
    ) -> bytes: ...


class LocalAnalyticsStorage:
    """Link atómico de un staging fsync: visible completo o ausente, incluso ante carrera."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _target(self, organization_id: UUID, artifact_id: UUID, format: str) -> Path:
        candidate = self.root / object_key(organization_id, artifact_id, format)
        candidate.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if candidate.parent.resolve().parent != self.root:
            raise StorageIntegrityError("storage_path_integrity_failure")
        if candidate.is_symlink():
            raise StorageIntegrityError("storage_path_integrity_failure")
        return candidate

    def publish(
        self,
        organization_id: UUID,
        artifact_id: UUID,
        format: str,
        content: bytes,
    ) -> PublishedObject:
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("export_size_limit")
        target = self._target(organization_id, artifact_id, format)
        metadata = PublishedObject(
            object_key(organization_id, artifact_id, format),
            hashlib.sha256(content).hexdigest(),
            len(content),
            format,
        )
        descriptor, staging_name = tempfile.mkstemp(prefix=".analytics-staging-", dir=target.parent)
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(staging, target)
            except FileExistsError:
                # Retry después de publicación/antes de commit o claim rival.
                existing = self.read(organization_id, artifact_id, metadata)
                if existing != content:
                    raise StorageIntegrityError("published_bytes_diverge") from None
            # La metadata se persiste por el worker, solo tras verificar el objeto publicado.
            self.read(organization_id, artifact_id, metadata)
            return metadata
        finally:
            staging.unlink(missing_ok=True)

    def read(
        self,
        organization_id: UUID,
        artifact_id: UUID,
        metadata: PublishedObject,
    ) -> bytes:
        expected_key = object_key(organization_id, artifact_id, metadata.format)
        if metadata.object_key != expected_key:
            raise StorageIntegrityError("artifact_identity_mismatch")
        target = self._target(organization_id, artifact_id, metadata.format)
        with target.open("rb") as stream:
            content = stream.read(MAX_ARTIFACT_BYTES + 1)
        if (
            len(content) != metadata.byte_size
            or len(content) > MAX_ARTIFACT_BYTES
            or hashlib.sha256(content).hexdigest() != metadata.sha256
        ):
            raise StorageIntegrityError("published_hash_or_size_diverges")
        return content
