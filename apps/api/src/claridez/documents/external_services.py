from __future__ import annotations

from typing import Any

from .acceptance import MANIFESTATION_TEXT, MANIFESTATION_VERSION
from .artifacts import verify_generated_artifact
from .errors import forbidden
from .external_access import authorize_session, external_token_scope
from .models import (
    ExternalAccessEvent,
    ExternalAccessGrant,
    ExternalTokenLocator,
    GeneratedArtifact,
)


def read_external_document(
    session_token: str, *, request_id: str = "", ip_hash: str = ""
) -> dict[str, Any]:
    with external_token_scope(session_token, kind=ExternalTokenLocator.Kind.SESSION):
        session = authorize_session(
            session_token,
            allowed_purposes=(
                ExternalAccessGrant.Purpose.READ,
                ExternalAccessGrant.Purpose.DOWNLOAD,
                ExternalAccessGrant.Purpose.ACCEPT,
            ),
        )
        version = session.grant.issued_version
        artifact = session.grant.artifact
        if artifact.state != GeneratedArtifact.State.AVAILABLE or artifact.verified_at is None:
            raise forbidden("El artefacto no estÃ¡ disponible.")
        ExternalAccessEvent.objects.create(
            organization_id=session.organization_id,
            grant=session.grant,
            kind="document_read",
            result="success",
            ip_hash=ip_hash,
            request_id=request_id[:128],
            occurred_at=session.last_seen_at,
        )
        return {
            "title": version.template_version.title,
            "issued_version_id": str(version.pk),
            "instrument_type": version.instrument.instrument_type,
            "version": version.version,
            "issued_at": version.issued_at.isoformat() if version.issued_at else None,
            "artifact": {
                "id": str(artifact.pk),
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "media_type": artifact.media_type,
            },
            "permissions": {
                "read": True,
                "download": session.grant.purpose
                in {ExternalAccessGrant.Purpose.DOWNLOAD, ExternalAccessGrant.Purpose.ACCEPT},
                "accept": session.grant.purpose == ExternalAccessGrant.Purpose.ACCEPT,
            },
            "manifestation": (
                {"text": MANIFESTATION_TEXT, "version": MANIFESTATION_VERSION}
                if session.grant.purpose == ExternalAccessGrant.Purpose.ACCEPT
                else None
            ),
        }


def download_external_artifact(
    session_token: str, *, request_id: str = "", ip_hash: str = ""
) -> tuple[bytes, str, str]:
    result = None
    media_type = ""
    filename = ""
    with external_token_scope(session_token, kind=ExternalTokenLocator.Kind.SESSION):
        session = authorize_session(
            session_token,
            allowed_purposes=(
                ExternalAccessGrant.Purpose.READ,
                ExternalAccessGrant.Purpose.DOWNLOAD,
                ExternalAccessGrant.Purpose.ACCEPT,
            ),
        )
        artifact = session.grant.artifact
        if artifact.state != GeneratedArtifact.State.AVAILABLE:
            raise forbidden("El artefacto no está disponible.")
        result = verify_generated_artifact(artifact)
        if result.verified:
            ExternalAccessEvent.objects.create(
                organization_id=session.organization_id,
                grant=session.grant,
                kind="artifact_delivered",
                result="success",
                ip_hash=ip_hash,
                request_id=request_id[:128],
                occurred_at=session.last_seen_at,
            )
        media_type = artifact.media_type
        filename = f"documento-{artifact.pk}.pdf"
    if result is None or result.content is None:
        raise forbidden("La entrega se bloqueó por una falla de integridad.")
    return result.content, media_type, filename
