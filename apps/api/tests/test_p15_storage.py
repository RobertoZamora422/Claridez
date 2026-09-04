from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from claridez.analytics.storage import LocalAnalyticsStorage, StorageIntegrityError, object_key


def test_publication_write_once_is_idempotent_and_private(tmp_path: Path) -> None:
    storage = LocalAnalyticsStorage(tmp_path)
    tenant, artifact = uuid4(), uuid4()
    content = b"metric,value\r\ncount,10\r\n"
    first = storage.publish(tenant, artifact, "csv", content)
    assert first == storage.publish(tenant, artifact, "csv", content)
    assert str(tenant) not in first.object_key and str(artifact) not in first.object_key
    assert storage.read(tenant, artifact, first) == content
    with pytest.raises(StorageIntegrityError):
        storage.publish(tenant, artifact, "csv", b"rival")
    assert storage.read(tenant, artifact, first) == content
    with pytest.raises(StorageIntegrityError):
        storage.read(uuid4(), artifact, first)


def test_concurrent_same_identity_same_bytes_is_one_publication(tmp_path: Path) -> None:
    storage = LocalAnalyticsStorage(tmp_path)
    tenant, artifact = uuid4(), uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: storage.publish(tenant, artifact, "csv", b"stable"), range(24))
        )
    assert len(set(results)) == 1
    assert len(list(tmp_path.rglob("*.csv"))) == 1
    assert list(tmp_path.rglob(".analytics-staging-*")) == []


def test_rival_hash_race_never_overwrites(tmp_path: Path) -> None:
    storage = LocalAnalyticsStorage(tmp_path)
    tenant, artifact = uuid4(), uuid4()

    def publish(content: bytes) -> object:
        try:
            return storage.publish(tenant, artifact, "csv", content)
        except StorageIntegrityError:
            return "terminal_integrity_failure"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [b"a", b"b"]))
    assert results.count("terminal_integrity_failure") == 1
    assert (tmp_path / object_key(tenant, artifact, "csv")).read_bytes() in {b"a", b"b"}


def test_retry_after_published_object_before_metadata_commit(tmp_path: Path) -> None:
    tenant, artifact = uuid4(), uuid4()
    first_process = LocalAnalyticsStorage(tmp_path)
    expected = first_process.publish(tenant, artifact, "csv", b"committed-by-storage")
    # Simula caída después del link pero antes de persistir la metadata PostgreSQL.
    retry_process = LocalAnalyticsStorage(tmp_path)
    assert retry_process.publish(tenant, artifact, "csv", b"committed-by-storage") == expected
    with pytest.raises(StorageIntegrityError):
        retry_process.read(tenant, artifact, replace(expected, byte_size=1))


def test_different_regeneration_requires_new_identity(tmp_path: Path) -> None:
    storage = LocalAnalyticsStorage(tmp_path)
    tenant, first_id, second_id = uuid4(), uuid4(), uuid4()
    first = storage.publish(tenant, first_id, "pdf", b"old")
    second = storage.publish(tenant, second_id, "pdf", b"new")
    assert first.object_key != second.object_key
    assert storage.read(tenant, first_id, first) == b"old"
