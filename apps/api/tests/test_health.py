"""Contrato de los únicos endpoints técnicos de la Iteración 2."""

from unittest.mock import MagicMock, patch

import pytest
from django.db import OperationalError
from django.test import Client
from django.urls import get_resolver


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.mark.parametrize("method", ["get", "head"])
def test_health_is_process_only_and_not_cached(client: Client, method: str) -> None:
    with patch("claridez.health.connections") as mocked_connections:
        response = getattr(client, method)("/health")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    if method == "get":
        assert response.json() == {"status": "ok"}
    else:
        assert response.content == b""
    mocked_connections.__getitem__.assert_not_called()


@pytest.mark.parametrize("method", ["get", "head"])
def test_ready_returns_generic_success(client: Client, method: str) -> None:
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor

    with patch("claridez.health.connections") as mocked_connections:
        mocked_connections.__getitem__.return_value = connection
        response = getattr(client, method)("/ready")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    if method == "get":
        assert response.json() == {"status": "ready"}
    else:
        assert response.content == b""
    cursor.execute.assert_called_once_with("SELECT 1")


@pytest.mark.parametrize("method", ["get", "head"])
def test_ready_hides_database_failure(client: Client, method: str) -> None:
    hidden_detail = "host=private user=private password=never-show"
    connection = MagicMock()
    connection.cursor.side_effect = OperationalError(hidden_detail)

    with patch("claridez.health.connections") as mocked_connections:
        mocked_connections.__getitem__.return_value = connection
        response = getattr(client, method)("/ready")

    assert response.status_code == 503
    assert response["Cache-Control"] == "no-store"
    if method == "get":
        body = response.content.decode("utf-8")
        assert response.json() == {"status": "unavailable"}
        assert hidden_detail not in body
        assert "host" not in body
        assert "password" not in body
    else:
        assert response.content == b""


def test_health_routes_and_authentication_group_are_the_only_root_routes() -> None:
    routes = {str(pattern.pattern) for pattern in get_resolver().url_patterns}
    assert routes == {"health", "ready", "api/v1/auth/"}
