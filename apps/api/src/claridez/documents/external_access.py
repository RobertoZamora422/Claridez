from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from claridez.organizations.tenant_scope import (
    TenantAuthorization,
    infrastructure_tenant_scope,
)

from .config import document_settings
from .errors import DocumentsError, conflict, unavailable
from .models import (
    AcceptanceChallenge,
    ExternalAccessEvent,
    ExternalAccessGrant,
    ExternalDocumentSession,
    ExternalRateLimitBucket,
    ExternalTokenLocator,
    GeneratedArtifact,
    IssuedInstrumentVersion,
)


def _hmac(value: str) -> str:
    configured = document_settings().token_hmac_key
    master_key = (
        configured.get_secret_value().encode()
        if configured is not None
        else settings.SECRET_KEY.encode()
    )
    key = hmac.new(
        master_key, b"claridez.documents.external-token-hmac-v1", hashlib.sha256
    ).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def _token() -> str:
    return secrets.token_urlsafe(48)


def _matches(stored: str, presented: str) -> bool:
    return hmac.compare_digest(stored, _hmac(presented))


@contextmanager
def external_token_scope(token: str, *, kind: str) -> Iterator[ExternalTokenLocator]:
    locator = ExternalTokenLocator.objects.filter(
        kind=kind, token_hmac=_hmac(token), expires_at__gt=timezone.now()
    ).first()
    if locator is None or not _matches(locator.token_hmac, token):
        raise unavailable("El acceso documental")
    with infrastructure_tenant_scope(locator.organization_id, purpose="external_document_session"):
        yield locator


@dataclass(frozen=True, slots=True)
class SecretGrant:
    grant: ExternalAccessGrant
    token: str


@dataclass(frozen=True, slots=True)
class SecretSession:
    session: ExternalDocumentSession
    token: str


@dataclass(frozen=True, slots=True)
class SecretChallenge:
    challenge: AcceptanceChallenge
    token: str


@transaction.atomic
def create_grant(
    authorization: TenantAuthorization,
    *,
    issued_version_id: UUID,
    purpose: str,
    expires_at: datetime,
    max_exchanges: int = 1,
) -> SecretGrant:
    now = timezone.now()
    if max_exchanges < 1 or max_exchanges > 20:
        raise DocumentsError("invalid_grant", "El límite de intercambios no es válido.")
    if expires_at <= now:
        raise DocumentsError("invalid_grant", "El vencimiento del grant no es válido.")
    version = IssuedInstrumentVersion.objects.get(
        organization_id=authorization.organization_id,
        pk=issued_version_id,
        state=IssuedInstrumentVersion.State.ISSUED,
    )
    artifact = version.artifacts.filter(is_emitted_original=True).first()
    if artifact is None:
        raise conflict("artifact_not_available", "La emisión no tiene artefacto original.")
    if artifact.state != GeneratedArtifact.State.AVAILABLE or artifact.verified_at is None:
        raise conflict(
            "artifact_not_available", "El artefacto no supera disponibilidad e integridad."
        )
    token = _token()
    grant = ExternalAccessGrant.objects.create(
        organization_id=authorization.organization_id,
        issued_version=version,
        artifact=artifact,
        purpose=ExternalAccessGrant.Purpose(purpose),
        token_hmac=_hmac(token),
        expires_at=expires_at,
        max_exchanges=max_exchanges,
        created_by_membership_id=authorization.membership_id,
    )
    ExternalTokenLocator.objects.create(
        kind=ExternalTokenLocator.Kind.GRANT,
        token_hmac=grant.token_hmac,
        organization_id=grant.organization_id,
        target_id=grant.pk,
        expires_at=grant.expires_at,
    )
    ExternalAccessEvent.objects.create(
        organization_id=grant.organization_id,
        grant=grant,
        kind="grant_created",
        result="success",
        detail=f"purpose:{grant.purpose}",
        occurred_at=now,
    )
    return SecretGrant(grant, token)


@transaction.atomic
def revoke_grant(authorization: TenantAuthorization, *, grant_id: UUID) -> ExternalAccessGrant:
    grant = ExternalAccessGrant.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=grant_id
    )
    if grant.revoked_at is None:
        grant.revoked_at = timezone.now()
        grant.revoked_by_membership_id = authorization.membership_id
        grant.save(update_fields=["revoked_at", "revoked_by_membership"])
        ExternalDocumentSession.objects.filter(grant=grant, revoked_at__isnull=True).update(
            revoked_at=grant.revoked_at
        )
        ExternalAccessEvent.objects.create(
            organization_id=grant.organization_id,
            grant=grant,
            kind="grant_revoked",
            result="success",
            detail=f"membership:{authorization.membership_id}",
            occurred_at=grant.revoked_at,
        )
    return grant


def exchange_grant(presented_token: str, *, request_id: str, ip_hash: str) -> SecretSession:
    with external_token_scope(presented_token, kind=ExternalTokenLocator.Kind.GRANT) as locator:
        now = timezone.now()
        candidate = (
            ExternalAccessGrant.objects.select_for_update()
            .filter(pk=locator.target_id, token_hmac=_hmac(presented_token))
            .first()
        )
        if (
            candidate is None
            or not _matches(candidate.token_hmac, presented_token)
            or candidate.revoked_at is not None
            or candidate.expires_at <= now
            or candidate.exchange_count >= candidate.max_exchanges
        ):
            raise unavailable("El enlace")
        candidate.exchange_count += 1
        candidate.save(update_fields=["exchange_count"])
        token = _token()
        session = ExternalDocumentSession.objects.create(
            organization_id=candidate.organization_id,
            grant=candidate,
            token_hmac=_hmac(token),
            expires_at=min(candidate.expires_at, now + timedelta(minutes=20)),
            last_seen_at=now,
        )
        ExternalTokenLocator.objects.create(
            kind=ExternalTokenLocator.Kind.SESSION,
            token_hmac=session.token_hmac,
            organization_id=session.organization_id,
            target_id=session.pk,
            expires_at=session.expires_at,
        )
        ExternalAccessEvent.objects.create(
            organization_id=candidate.organization_id,
            grant=candidate,
            kind="grant_exchanged",
            result="success",
            ip_hash=ip_hash,
            request_id=request_id,
            occurred_at=now,
        )
        return SecretSession(session, token)


def authorize_session(token: str, *, allowed_purposes: tuple[str, ...]) -> ExternalDocumentSession:
    session = (
        ExternalDocumentSession.objects.select_for_update()
        .select_related("grant", "grant__issued_version", "grant__artifact")
        .filter(token_hmac=_hmac(token))
        .first()
    )
    now = timezone.now()
    if (
        session is None
        or not _matches(session.token_hmac, token)
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.grant.revoked_at is not None
        or session.grant.expires_at <= now
        or session.grant.purpose not in allowed_purposes
    ):
        raise unavailable("La sesión documental")
    session.last_seen_at = max(session.last_seen_at, now)
    session.save(update_fields=["last_seen_at"])
    return session


def create_acceptance_challenge(
    session_token: str, *, request_id: str = "", ip_hash: str = ""
) -> SecretChallenge:
    with external_token_scope(session_token, kind=ExternalTokenLocator.Kind.SESSION):
        session = authorize_session(
            session_token, allowed_purposes=(ExternalAccessGrant.Purpose.ACCEPT,)
        )
        existing = AcceptanceChallenge.objects.filter(
            grant=session.grant,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).first()
        if existing is not None:
            existing.revoked_at = timezone.now()
            existing.save(update_fields=["revoked_at"])
            ExternalAccessEvent.objects.create(
                organization_id=existing.organization_id,
                grant=existing.grant,
                challenge=existing,
                kind="challenge_revoked",
                result="superseded",
                ip_hash=ip_hash,
                request_id=request_id[:128],
                occurred_at=existing.revoked_at,
            )
        token = _token()
        challenge = AcceptanceChallenge.objects.create(
            organization_id=session.organization_id,
            grant=session.grant,
            issued_version=session.grant.issued_version,
            artifact=session.grant.artifact,
            token_hmac=_hmac(token),
            expires_at=min(session.expires_at, timezone.now() + timedelta(minutes=10)),
        )
        ExternalTokenLocator.objects.create(
            kind=ExternalTokenLocator.Kind.CHALLENGE,
            token_hmac=challenge.token_hmac,
            organization_id=challenge.organization_id,
            target_id=challenge.pk,
            expires_at=challenge.expires_at,
        )
        ExternalAccessEvent.objects.create(
            organization_id=challenge.organization_id,
            grant=challenge.grant,
            challenge=challenge,
            kind="challenge_created",
            result="success",
            ip_hash=ip_hash,
            request_id=request_id[:128],
            occurred_at=challenge.created_at,
        )
        return SecretChallenge(challenge, token)


def token_hash(value: str) -> str:
    return _hmac(value)


@transaction.atomic
def enforce_rate_limit(client_address: str, *, limit: int = 20) -> str:
    now = timezone.now()
    window = now.replace(second=0, microsecond=0)
    key_hash = _hmac(f"external-rate:{client_address or 'unknown'}")
    bucket, _ = ExternalRateLimitBucket.objects.select_for_update().get_or_create(
        key_hash=key_hash, window_start=window
    )
    if bucket.request_count >= limit:
        raise DocumentsError(
            "rate_limited", "Demasiadas solicitudes. Inténtalo más tarde.", status_code=429
        )
    bucket.request_count += 1
    bucket.save(update_fields=["request_count", "updated_at"])
    return key_hash
