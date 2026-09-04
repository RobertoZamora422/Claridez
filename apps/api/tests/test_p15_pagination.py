from __future__ import annotations

from dataclasses import replace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core import signing
from django.db.models import QuerySet

from claridez.analytics.models import ReportRevision
from claridez.analytics.pagination import CURSOR_SALT, MAX_PAGE_BYTES, cursor_position, page
from claridez.analytics.serializers import HistoryQuerySerializer
from claridez.organizations.exceptions import AuthorizationDenied
from tests.test_p15_query import NOW, authorization


def rows(count: int) -> QuerySet[ReportRevision]:
    query = MagicMock()
    query.order_by.return_value.__getitem__.return_value = tuple(
        ReportRevision(id=uuid4(), created_at=NOW) for _ in range(count)
    )
    return cast(QuerySet[ReportRevision], query)


def test_cursor_is_bound_to_tenant_membership_and_collection() -> None:
    auth = authorization()
    result = page(rows(3), auth, "reports", lambda row: {"id": str(row.pk)}, limit=2)
    token = str(result["next_cursor"])
    assert len(cast(list[object], result["results"])) == 2
    assert cursor_position(token, auth, "reports")[0] == NOW
    for other, collection in (
        (replace(auth, organization_id=uuid4()), "reports"),
        (replace(auth, membership_id=uuid4()), "reports"),
        (auth, "executions"),
    ):
        with pytest.raises(ValueError, match="invalid_history_cursor"):
            cursor_position(token, other, collection)
    with pytest.raises(ValueError, match="invalid_history_cursor"):
        cursor_position(token + "tampered", auth, "reports")


def test_denied_rows_do_not_end_history_or_leak_their_serialized_data() -> None:
    def denied(_: ReportRevision) -> dict[str, object]:
        raise AuthorizationDenied()

    result = page(rows(3), authorization(), "reports", denied, limit=2)
    assert result["results"] == []
    assert result["next_cursor"] is not None


def test_history_payload_is_bounded_without_skipping_the_next_authorized_item() -> None:
    result = page(
        rows(3),
        authorization(),
        "reports",
        lambda _: {"title": "x" * (MAX_PAGE_BYTES // 2)},
        limit=3,
    )
    assert len(cast(list[object], result["results"])) == 1
    assert result["next_cursor"] is not None
    with pytest.raises(ValueError, match="history_item_exceeds_payload_limit"):
        page(rows(1), authorization(), "reports", lambda _: {"title": "x" * MAX_PAGE_BYTES})


def test_finished_page_has_no_cursor_and_uses_one_bounded_queryset() -> None:
    query = rows(2)
    result = page(query, authorization(), "reports", lambda row: {"id": str(row.pk)}, limit=2)
    assert result["next_cursor"] is None
    cast(MagicMock, query).order_by.assert_called_once_with("-created_at", "-id")
    cast(MagicMock, query).order_by.return_value.__getitem__.assert_called_once_with(slice(None, 3))


@pytest.mark.parametrize(
    "data", [{"limit": 0}, {"limit": 51}, {"offset": 10}, {"cursor": "x" * 2049}]
)
def test_history_request_is_strict(data: dict[str, object]) -> None:
    assert not HistoryQuerySerializer(data=data).is_valid()


def test_even_signed_cursor_rejects_naive_timestamp() -> None:
    auth = authorization()
    cursor = signing.dumps(
        {
            "scope": [str(auth.organization_id), str(auth.membership_id), "reports"],
            "at": "2026-09-04T12:00:00",
            "id": str(uuid4()),
        },
        salt=CURSOR_SALT,
    )
    with pytest.raises(ValueError, match="invalid_history_cursor"):
        cursor_position(cursor, auth, "reports")
