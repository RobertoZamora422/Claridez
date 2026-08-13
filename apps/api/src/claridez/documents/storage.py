from __future__ import annotations

import base64
import hashlib
import io
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol, cast
from uuid import uuid4

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from .config import document_settings
from .errors import DocumentsError


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str


class PrivateObjectStorage(Protocol):
    def put(
        self, *, key: str, stream: BinaryIO, size_bytes: int, sha256: str, media_type: str
    ) -> StoredObject: ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...


def opaque_object_key(category: str) -> str:
    if category not in {"generated", "quarantine"}:
        raise ValueError("categoría de almacenamiento desconocida")
    identifier = uuid4().hex
    return f"{category}/{identifier[:2]}/{identifier[2:]}"


def opaque_evidence_key(category: str, identifier: str) -> str:
    compact = identifier.replace("-", "").lower()
    if (
        category != "generated"
        or len(compact) != 32
        or not all(character in "0123456789abcdef" for character in compact)
    ):
        raise ValueError("identificador de evidencia no válido")
    return f"{category}/{compact[:2]}/{compact[2:]}"


def stream_sha256(stream: BinaryIO, *, max_bytes: int | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise DocumentsError("file_too_large", "El archivo excede el límite permitido.")
        digest.update(chunk)
    stream.seek(0)
    return size, digest.hexdigest()


class FilesystemPrivateStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or "\\" in key or key.startswith("/") or ".." in key.split("/"):
            raise DocumentsError("invalid_storage_key", "La clave de almacenamiento no es válida.")
        target = (self.root / Path(*key.split("/"))).resolve()
        if self.root not in target.parents:
            raise DocumentsError("invalid_storage_key", "La clave de almacenamiento no es válida.")
        return target

    def put(
        self, *, key: str, stream: BinaryIO, size_bytes: int, sha256: str, media_type: str
    ) -> StoredObject:
        del media_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_name(f".{target.name}.{uuid4().hex}.pending")
        digest = hashlib.sha256()
        observed = 0
        try:
            with pending.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    observed += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if observed != size_bytes or digest.hexdigest() != sha256:
                raise DocumentsError("integrity_mismatch", "La integridad del objeto no coincide.")
            try:
                os.link(pending, target)
            except FileExistsError as error:
                raise DocumentsError(
                    "object_exists", "La evidencia no puede sobrescribirse.", status_code=409
                ) from error
        except FileExistsError as error:
            raise DocumentsError(
                "object_exists", "La evidencia no puede sobrescribirse.", status_code=409
            ) from error
        finally:
            pending.unlink(missing_ok=True)
            stream.seek(0)
        return StoredObject(key, observed, sha256)

    def open(self, key: str) -> BinaryIO:
        try:
            return self._path(key).open("rb")
        except FileNotFoundError as error:
            raise DocumentsError(
                "object_missing", "El objeto privado no está disponible.", status_code=404
            ) from error

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3PrivateStorage:
    def __init__(self) -> None:
        config = document_settings()
        import boto3  # type: ignore[import-untyped]

        self.bucket = config.s3_bucket or ""
        self.sse = config.s3_sse
        self.kms_key = config.s3_kms_key_id
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=config.s3_endpoint_url,
            region_name=config.s3_region,
            aws_access_key_id=(
                config.s3_access_key_id.get_secret_value() if config.s3_access_key_id else None
            ),
            aws_secret_access_key=(
                config.s3_secret_access_key.get_secret_value()
                if config.s3_secret_access_key
                else None
            ),
        )

    def put(
        self, *, key: str, stream: BinaryIO, size_bytes: int, sha256: str, media_type: str
    ) -> StoredObject:
        parameters: dict[str, object] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": stream,
            "ContentLength": size_bytes,
            "ContentType": media_type,
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256)).decode(),
            "IfNoneMatch": "*",
            "ServerSideEncryption": self.sse,
            "Metadata": {"claridez-sha256": sha256},
        }
        if self.kms_key:
            parameters["SSEKMSKeyId"] = self.kms_key
        try:
            self.client.put_object(**parameters)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in {409, 412}:
                raise DocumentsError(
                    "object_exists", "La evidencia no puede sobrescribirse.", status_code=409
                ) from error
            raise DocumentsError(
                "storage_unavailable",
                "El almacenamiento privado no está disponible.",
                status_code=503,
            ) from error
        finally:
            stream.seek(0)
        return StoredObject(key, size_bytes, sha256)

    def open(self, key: str) -> BinaryIO:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise DocumentsError(
                    "object_missing", "El objeto privado no está disponible.", status_code=404
                ) from error
            raise DocumentsError(
                "storage_unavailable",
                "El almacenamiento privado no está disponible.",
                status_code=503,
            ) from error
        return cast(BinaryIO, response["Body"])

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise DocumentsError(
                "storage_unavailable",
                "El almacenamiento privado no está disponible.",
                status_code=503,
            ) from error
        return True


def private_storage() -> PrivateObjectStorage:
    config = document_settings()
    if config.storage_backend == "s3":
        return S3PrivateStorage()
    return FilesystemPrivateStorage(config.storage_root)


def bytes_stream(value: bytes) -> io.BytesIO:
    return io.BytesIO(value)


def iter_chunks(stream: BinaryIO, size: int = 64 * 1024) -> Iterator[bytes]:
    while chunk := stream.read(size):
        yield chunk
