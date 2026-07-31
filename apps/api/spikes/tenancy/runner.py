"""Ejecutar el ciclo completo del spike y eliminar siempre su base desechable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spikes.tenancy import SPIKE_DATABASE_NAME
from spikes.tenancy.database import (
    cleanup_database,
    collect_catalog_evidence,
    database_exists,
    database_names,
    grant_runtime_privileges,
    prepare_database,
    verify_preconditions,
)

API_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = API_ROOT.parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "tmp" / "tenancy-spike"
TEST_EVIDENCE_PATH = EVIDENCE_ROOT / "test-evidence.json"
RESULTS_PATH = EVIDENCE_ROOT / "results.json"
COVERAGE_XML_PATH = EVIDENCE_ROOT / "coverage.xml"
COVERAGE_HTML_PATH = EVIDENCE_ROOT / "htmlcov"


def _run(command: list[str], *, environment: dict[str, str]) -> None:
    subprocess.run(command, cwd=API_ROOT, env=environment, check=True)


def _migrate(environment: dict[str, str]) -> None:
    _run(
        [
            sys.executable,
            "manage.py",
            "migrate",
            "--settings=spikes.tenancy.settings",
            "--database=migrator",
            "--noinput",
        ],
        environment=environment,
    )


def _test(environment: dict[str, str]) -> None:
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "spikes/tenancy/pytest.ini",
            "-p",
            "no:django",
            "-m",
            "tenancy_spike",
            "spikes/tenancy/tests",
            "--cov=spikes.tenancy",
            "--cov-branch",
            "--cov-report=term-missing",
            f"--cov-report=xml:{COVERAGE_XML_PATH}",
            f"--cov-report=html:{COVERAGE_HTML_PATH}",
        ],
        environment=environment,
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write_results(results: dict[str, Any]) -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "spikes.tenancy.settings"
    environment["CLARIDEZ_SPIKE_TEST_EVIDENCE"] = str(TEST_EVIDENCE_PATH)
    results: dict[str, Any] = {
        "database": SPIKE_DATABASE_NAME,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "status": "running",
    }
    exit_code = 1
    databases_before = database_names() - {SPIKE_DATABASE_NAME}
    try:
        prepare_database(replace_existing=True)
        results["lifecycle_prepare"] = "passed"
        _migrate(environment)
        results["lifecycle_migrate_as"] = "claridez_migrator"
        grant_runtime_privileges()
        results["lifecycle_grants"] = "passed"
        results["catalog_before_tests"] = verify_preconditions()
        _test(environment)
        results["tests"] = _read_json(TEST_EVIDENCE_PATH)
        unexpected_databases = database_names() - databases_before - {SPIKE_DATABASE_NAME}
        if unexpected_databases:
            raise RuntimeError("La suite creó una base fuera del ciclo autorizado.")
        results["unexpected_databases_created"] = 0

        from spikes.tenancy.benchmark import run_benchmark

        results["benchmark"] = run_benchmark()
        results["catalog_after_tests"] = collect_catalog_evidence()
        verify_preconditions()
        results["ownership_unchanged_after_tests"] = True
        results["status"] = "passed"
        exit_code = 0
    except (Exception, subprocess.CalledProcessError) as error:
        results["status"] = "failed"
        results["failure_class"] = type(error).__name__
        results["tests"] = _read_json(TEST_EVIDENCE_PATH)
    finally:
        try:
            from django.conf import settings as django_settings
            from django.db import connections

            if django_settings.configured:
                connections.close_all()
        except (ImportError, RuntimeError):
            pass
        try:
            if database_exists():
                cleanup_database(confirmed=True)
            results["database_removed"] = not database_exists()
            results["database_catalog_restored"] = database_names() == databases_before
        except Exception as cleanup_error:
            results["database_removed"] = False
            results["cleanup_failure_class"] = type(cleanup_error).__name__
            exit_code = 1
        results["finished_at_utc"] = datetime.now(UTC).isoformat()
        _write_results(results)

    print(
        json.dumps(
            {
                "database": SPIKE_DATABASE_NAME,
                "database_removed": results.get("database_removed", False),
                "evidence": RESULTS_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
                "status": results["status"],
            },
            separators=(",", ":"),
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
