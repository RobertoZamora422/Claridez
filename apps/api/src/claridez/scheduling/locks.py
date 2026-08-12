from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import connection


def lock_spaces(organization_id: UUID, space_ids: Iterable[UUID]) -> tuple[UUID, ...]:
    ordered = tuple(sorted(set(space_ids), key=str))
    with connection.cursor() as cursor:
        for space_id in ordered:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{organization_id}:{space_id}",),
            )
    return ordered
