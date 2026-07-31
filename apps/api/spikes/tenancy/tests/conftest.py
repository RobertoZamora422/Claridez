"""Fixtures contra la base preparada y migrada previamente por el runner."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import django
import pytest

API_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = API_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spikes.tenancy.settings")
django.setup()

from django.db import connections  # noqa: E402

from spikes.tenancy.database import verify_preconditions  # noqa: E402

ORGANIZATION_A = UUID("11111111-1111-4111-8111-111111111111")
ORGANIZATION_B = UUID("22222222-2222-4222-8222-222222222222")
APP_RECORD_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
APP_RECORD_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
RLS_RECORD_A = UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc1")
RLS_RECORD_B = UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd2")


@dataclass(frozen=True, slots=True)
class Organizations:
    a: UUID = ORGANIZATION_A
    b: UUID = ORGANIZATION_B


class EvidenceRecorder:
    """Conservar únicamente clases de resultado, conteos y hechos técnicos."""

    def __init__(self) -> None:
        self.observations: dict[str, Any] = {}

    def record(self, key: str, value: Any) -> None:
        self.observations[key] = value


RECORDER = EvidenceRecorder()
TEST_OUTCOMES = {"passed": 0, "failed": 0, "skipped": 0}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "tenancy_spike: experimento contra base desechable")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when != "call":
        return
    if report.passed:
        TEST_OUTCOMES["passed"] += 1
    elif report.failed:
        TEST_OUTCOMES["failed"] += 1
    elif report.skipped:
        TEST_OUTCOMES["skipped"] += 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    path_value = os.environ.get("CLARIDEZ_SPIKE_TEST_EVIDENCE")
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "exit_status": exitstatus,
                "outcomes": TEST_OUTCOMES,
                "observations": RECORDER.observations,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture(scope="session", autouse=True)
def database_contract() -> None:
    """Fallar si el runner no preparó propietarios y roles correctos."""
    verify_preconditions()


@pytest.fixture(autouse=True)
def synthetic_rows() -> Iterator[Organizations]:
    """Restablecer datos sintéticos como migrador antes de cada prueba."""
    migrator = connections["migrator"]
    with migrator.cursor() as cursor:
        cursor.execute("ALTER TABLE claridez_spike_rls_record NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE claridez_spike_rls_child NO FORCE ROW LEVEL SECURITY")
        cursor.execute(
            "TRUNCATE claridez_spike_app_child, claridez_spike_rls_child, "
            "claridez_spike_app_record, claridez_spike_rls_record, "
            "claridez_spike_rls_default_deny, claridez_spike_organization CASCADE"
        )
        cursor.execute(
            "INSERT INTO claridez_spike_organization (id, label) VALUES (%s, %s), (%s, %s)",
            (ORGANIZATION_A, "organization-a", ORGANIZATION_B, "organization-b"),
        )
        cursor.execute(
            """
            INSERT INTO claridez_spike_app_record (id, organization_id, external_key, payload)
            VALUES (%s, %s, 'key-a', 'synthetic-a'), (%s, %s, 'key-b', 'synthetic-b')
            """,
            (APP_RECORD_A, ORGANIZATION_A, APP_RECORD_B, ORGANIZATION_B),
        )
        cursor.execute(
            """
            INSERT INTO claridez_spike_rls_record (id, organization_id, external_key, payload)
            VALUES (%s, %s, 'key-a', 'synthetic-a'), (%s, %s, 'key-b', 'synthetic-b')
            """,
            (RLS_RECORD_A, ORGANIZATION_A, RLS_RECORD_B, ORGANIZATION_B),
        )
    yield Organizations()
    for connection in connections.all():
        if connection.in_atomic_block:
            connection.rollback()


@pytest.fixture
def evidence() -> EvidenceRecorder:
    return RECORDER


@pytest.fixture(scope="session", autouse=True)
def close_connections_at_end() -> Iterator[None]:
    yield
    connections.close_all()
