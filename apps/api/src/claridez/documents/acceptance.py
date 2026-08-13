from __future__ import annotations

import hmac
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .artifacts import verify_generated_artifact
from .errors import DocumentsError, conflict, unavailable
from .external_access import authorize_session, external_token_scope, token_hash
from .models import (
    AcceptanceChallenge,
    AcceptanceEvidence,
    ExternalAccessEvent,
    ExternalAccessGrant,
    ExternalTokenLocator,
    GeneratedArtifact,
)

MANIFESTATION_VERSION = "claridez-acceptance-es-v1"
MANIFESTATION_TEXT = (
    "Declaro que he leído el documento identificado, que corresponde a los bytes mostrados "
    "y descargables en esta sesión, y manifiesto expresamente mi aceptación electrónica."
)
MECHANISM_VERSION = "secure-link-session-challenge-v1"


@dataclass(frozen=True, slots=True)
class AcceptanceRequestEvidence:
    asserted_name: str
    ip_address: str | None
    user_agent: str
    request_id: str
    correlation_id: str
    timezone_name: str


def accept(
    session_token: str,
    *,
    challenge_token: str,
    manifestation_version: str,
    affirmative: bool,
    evidence: AcceptanceRequestEvidence,
) -> AcceptanceEvidence:
    integrity_verified = False
    with external_token_scope(session_token, kind=ExternalTokenLocator.Kind.SESSION):
        session = authorize_session(
            session_token, allowed_purposes=(ExternalAccessGrant.Purpose.ACCEPT,)
        )
        artifact = GeneratedArtifact.objects.select_for_update().get(pk=session.grant.artifact_id)
        if artifact.state == GeneratedArtifact.State.AVAILABLE:
            integrity_verified = verify_generated_artifact(artifact).verified
        if integrity_verified:
            return _accept_in_scope(
                session_token,
                challenge_token=challenge_token,
                manifestation_version=manifestation_version,
                affirmative=affirmative,
                evidence=evidence,
            )
    raise unavailable("El artefacto")


@transaction.atomic
def _accept_in_scope(
    session_token: str,
    *,
    challenge_token: str,
    manifestation_version: str,
    affirmative: bool,
    evidence: AcceptanceRequestEvidence,
) -> AcceptanceEvidence:
    session = authorize_session(
        session_token, allowed_purposes=(ExternalAccessGrant.Purpose.ACCEPT,)
    )
    if not affirmative or manifestation_version != MANIFESTATION_VERSION:
        raise DocumentsError("affirmation_required", "Se requiere una manifestación afirmativa.")
    now = timezone.now()
    challenge = (
        AcceptanceChallenge.objects.select_for_update()
        .filter(
            grant=session.grant,
            token_hmac=token_hash(challenge_token),
        )
        .first()
    )
    if (
        challenge is None
        or not hmac.compare_digest(challenge.token_hmac, token_hash(challenge_token))
        or challenge.revoked_at is not None
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
        or challenge.issued_version_id != session.grant.issued_version_id
        or challenge.artifact_id != session.grant.artifact_id
    ):
        raise conflict("invalid_or_consumed_challenge", "El challenge no es válido.")
    artifact = GeneratedArtifact.objects.select_for_update().get(pk=challenge.artifact_id)
    if artifact.state != GeneratedArtifact.State.AVAILABLE or artifact.verified_at is None:
        raise unavailable("El artefacto")
    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at"])
    counterparty = challenge.issued_version.snapshot["counterparty"]
    acceptance = AcceptanceEvidence.objects.create(
        organization_id=session.organization_id,
        challenge=challenge,
        issued_version=challenge.issued_version,
        artifact=artifact,
        artifact_sha256=artifact.sha256,
        manifestation_text=MANIFESTATION_TEXT,
        manifestation_version=MANIFESTATION_VERSION,
        acceptor_projection={
            "intended_counterparty": counterparty,
            "asserted_name": " ".join(evidence.asserted_name.split()),
        },
        attribution_method="secure_link_self_assertion",
        authentication_result={"grant_id": str(session.grant_id), "session_id": str(session.pk)},
        mechanism_version=MECHANISM_VERSION,
        accepted_at=now,
        timezone_name=evidence.timezone_name,
        ip_address=evidence.ip_address,
        user_agent=evidence.user_agent[:500],
        request_id=evidence.request_id[:128],
        correlation_id=evidence.correlation_id[:128],
    )
    ExternalAccessEvent.objects.create(
        organization_id=session.organization_id,
        grant=session.grant,
        challenge=challenge,
        kind="acceptance_completed",
        result="success",
        request_id=evidence.request_id[:128],
        occurred_at=now,
    )
    return acceptance
