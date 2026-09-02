"""Primitivas técnicas compartidas; no constituyen autoridad de dominio."""

import hashlib
import hmac
from uuid import UUID

from django.conf import settings


def short_single_use_code(reference: UUID) -> str:
    digest = hmac.new(
        str(settings.SECRET_KEY).encode(), f"external-code:{reference}".encode(), hashlib.sha256
    ).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"
