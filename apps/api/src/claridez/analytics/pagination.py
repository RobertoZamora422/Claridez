"""Keyset privado con cursor firmado y presupuesto de materialización por página."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from django.core import signing
from django.db.models import Q, QuerySet

from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import TenantModel

MAX_PAGE_ROWS = 50
MAX_PAGE_BYTES = 512 * 1024
CURSOR_SALT = "claridez.analytics.history@1"


def cursor_position(
    cursor: str,
    auth: TenantAuthorization,
    collection: str,
) -> tuple[datetime, UUID]:
    try:
        data = signing.loads(cursor, salt=CURSOR_SALT, max_age=86400)
        if not isinstance(data, dict) or data.get("scope") != [
            str(auth.organization_id),
            str(auth.membership_id),
            collection,
        ]:
            raise ValueError("history_cursor_scope_mismatch")
        at, identifier = datetime.fromisoformat(data["at"]), UUID(data["id"])
        if at.utcoffset() is None:
            raise ValueError("history_cursor_without_offset")
        return at, identifier
    except (signing.BadSignature, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid_history_cursor") from error


def page[T: TenantModel](
    rows: QuerySet[T],
    auth: TenantAuthorization,
    collection: str,
    serialize: Callable[[T], dict[str, object]],
    *,
    cursor: str = "",
    limit: int = MAX_PAGE_ROWS,
) -> dict[str, object]:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE_ROWS:
        raise ValueError("invalid_history_page_limit")
    if cursor:
        at, identifier = cursor_position(cursor, auth, collection)
        rows = rows.filter(Q(created_at__lt=at) | Q(created_at=at, pk__lt=identifier))
    candidates = tuple(rows.order_by("-created_at", "-id")[: limit + 1])
    results: list[dict[str, object]] = []
    consumed = 0
    size = 2048  # Reserva para envoltura y cursor; no devuelve un payload sin acotar.
    for row in candidates[:limit]:
        try:
            value = serialize(row)
        except AuthorizationDenied:
            consumed += 1
            continue
        amount = (
            len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        )
        if size + amount > MAX_PAGE_BYTES:
            if not consumed:
                raise ValueError("history_item_exceeds_payload_limit")
            break
        results.append(value)
        consumed += 1
        size += amount
    next_cursor = None
    if consumed and consumed < len(candidates):
        last = candidates[consumed - 1]
        next_cursor = signing.dumps(
            {
                "scope": [str(auth.organization_id), str(auth.membership_id), collection],
                "at": last.created_at.isoformat(),
                "id": str(last.pk),
            },
            salt=CURSOR_SALT,
            compress=True,
        )
    return {"results": results, "next_cursor": next_cursor}
