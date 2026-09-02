from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .errors import PortalError
from .models import AntiAbuseTokenUse, PortalRateLimitBucket


def digest(value: str, *, purpose: str) -> str:
    return hmac.new(
        str(settings.SECRET_KEY).encode(), f"{purpose}:{value}".encode(), hashlib.sha256
    ).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def random_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def payload_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def consume_rate_limit(*, action: str, key: str, limit: int, window_seconds: int) -> None:
    now = timezone.now()
    epoch = int(now.timestamp()) // window_seconds * window_seconds
    window = datetime.fromtimestamp(epoch, tz=timezone.get_current_timezone())
    key_hmac = digest(key, purpose=f"rate:{action}")
    exceeded = False
    with transaction.atomic():
        bucket, _ = PortalRateLimitBucket.objects.select_for_update().get_or_create(
            key_hmac=key_hmac,
            action=action,
            window_started_at=window,
        )
        if bucket.blocked_until and bucket.blocked_until > now:
            raise PortalError("rate_limited", "Intenta nuevamente más tarde.", status=429)
        bucket.count += 1
        if bucket.count > limit:
            bucket.blocked_until = now + timedelta(seconds=window_seconds)
            bucket.save(update_fields=["count", "blocked_until"])
            exceeded = True
        else:
            bucket.save(update_fields=["count"])
    if exceeded:
        raise PortalError("rate_limited", "Intenta nuevamente más tarde.", status=429)


@dataclass(frozen=True, slots=True)
class AntiAbuseResult:
    valid: bool
    hostname: str
    action: str


class DeterministicAntiAbuse:
    def verify(self, token: str, *, action: str, hostname: str, remote_ip: str) -> AntiAbuseResult:
        del remote_ip
        return AntiAbuseResult(token.startswith("test-pass:") and len(token) > 20, hostname, action)


class TurnstileAntiAbuse:
    def verify(self, token: str, *, action: str, hostname: str, remote_ip: str) -> AntiAbuseResult:
        payload = urllib.parse.urlencode(
            {
                "secret": settings.PORTAL_TURNSTILE_SECRET_KEY,
                "response": token,
                "remoteip": remote_ip,
            }
        ).encode()
        request = urllib.request.Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                data = json.loads(response.read())
        except (OSError, ValueError):
            return AntiAbuseResult(False, "", "")
        return AntiAbuseResult(
            bool(data.get("success")), str(data.get("hostname", "")), str(data.get("action", ""))
        )


def verify_antiabuse(token: str, *, action: str, hostname: str, remote_ip: str) -> None:
    provider = (
        TurnstileAntiAbuse()
        if settings.PORTAL_ANTIABUSE_PROVIDER == "turnstile"
        else DeterministicAntiAbuse()
    )
    result = provider.verify(token, action=action, hostname=hostname, remote_ip=remote_ip)
    expected_hosts = set(settings.PORTAL_TURNSTILE_EXPECTED_HOSTNAMES)
    if (
        not result.valid
        or result.action != action
        or result.hostname != hostname
        or (expected_hosts and result.hostname not in expected_hosts)
    ):
        raise PortalError("antiabuse_failed", "No fue posible validar la solicitud.", status=400)
    try:
        with transaction.atomic():
            AntiAbuseTokenUse.objects.create(
                token_hmac=digest(token, purpose="antiabuse"), action=action, hostname=hostname
            )
    except IntegrityError:
        raise PortalError(
            "antiabuse_replay", "No fue posible validar la solicitud.", status=400
        ) from None
