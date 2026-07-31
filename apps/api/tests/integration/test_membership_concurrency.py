"""Pruebas deterministas de bloqueos organizacionales en PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from typing import Any

import pytest
from django.db import close_old_connections, connection, connections, transaction

from claridez.identity.models import User
from claridez.organizations.exceptions import LastActiveOwnerRequired
from claridez.organizations.models import Membership, Organization
from claridez.organizations.services import (
    add_membership,
    bootstrap_organization,
    change_membership_role,
    create_organization,
    transition_membership,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
PASSWORD = "A-strong-concurrency-password-42!"
Operation = Callable[[], Any]


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


def _two_owner_organization(prefix: str) -> tuple[Organization, Membership, Membership]:
    first_user = _active_user(f"{prefix}-first@example.com")
    creation = create_organization(owner_user_id=first_user.pk, name=f"Organization {prefix}")
    second_user = _active_user(f"{prefix}-second@example.com")
    second_owner = add_membership(
        organization_id=creation.organization.pk,
        user_id=second_user.pk,
        role=Membership.Role.OWNER,
    )
    return creation.organization, creation.owner_membership, second_owner


def _serialized_worker(
    *,
    barrier: Barrier,
    backend_pids: Queue[int],
    first_completed: Event,
    allow_commit: Event,
    operation: Operation,
) -> tuple[str, Any]:
    close_old_connections()
    database = connections["default"]
    try:
        with transaction.atomic():
            with database.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend_pids.put(cursor.fetchone()[0])
            barrier.wait(timeout=5)
            value = operation()
            first_completed.set()
            if not allow_commit.wait(timeout=5):
                raise TimeoutError("La prueba no liberó el commit.")
        return "ok", value
    except LastActiveOwnerRequired:
        return "last_owner", None
    finally:
        database.close()


def _observe_waiting_lock(backend_pids: list[int]) -> None:
    for _ in range(200):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM pg_stat_activity
                WHERE pid = ANY(%s) AND wait_event_type = 'Lock'
                """,
                (backend_pids,),
            )
            if cursor.fetchone()[0] >= 1:
                return
        Event().wait(0.01)
    pytest.fail("No se observó la espera por bloqueo en PostgreSQL.")


def _run_serialized_pair(first: Operation, second: Operation) -> list[tuple[str, Any]]:
    barrier = Barrier(3)
    backend_pids: Queue[int] = Queue()
    first_completed = Event()
    allow_commit = Event()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _serialized_worker,
                barrier=barrier,
                backend_pids=backend_pids,
                first_completed=first_completed,
                allow_commit=allow_commit,
                operation=operation,
            )
            for operation in (first, second)
        ]
        pids = [backend_pids.get(timeout=5), backend_pids.get(timeout=5)]
        barrier.wait(timeout=5)
        try:
            assert first_completed.wait(timeout=5)
            _observe_waiting_lock(pids)
        finally:
            allow_commit.set()
        return [future.result(timeout=5) for future in futures]


@pytest.mark.parametrize("operation", ["demote", "revoke", "suspend"])
def test_two_concurrent_owner_removals_leave_exactly_one_owner(operation: str) -> None:
    organization, first_owner, second_owner = _two_owner_organization(operation)

    def mutate(membership_id: Any) -> None:
        if operation == "demote":
            change_membership_role(
                organization_id=organization.pk,
                membership_id=membership_id,
                target_role=Membership.Role.ADMINISTRATOR,
            )
        else:
            transition_membership(
                organization_id=organization.pk,
                membership_id=membership_id,
                target_status=(
                    Membership.Status.REVOKED
                    if operation == "revoke"
                    else Membership.Status.SUSPENDED
                ),
            )

    results = _run_serialized_pair(
        lambda: mutate(first_owner.pk),
        lambda: mutate(second_owner.pk),
    )

    assert sorted(status for status, _ in results) == ["last_owner", "ok"]
    assert (
        Membership.objects.filter(
            organization=organization,
            role=Membership.Role.OWNER,
            status=Membership.Status.ACTIVE,
        ).count()
        == 1
    )


def test_concurrent_promotions_are_serialized_and_both_succeed() -> None:
    owner = _active_user("promotion-owner@example.com")
    organization = create_organization(owner_user_id=owner.pk, name="Promotions").organization
    first_user = _active_user("promotion-first@example.com")
    second_user = _active_user("promotion-second@example.com")
    first = add_membership(
        organization_id=organization.pk,
        user_id=first_user.pk,
        role=Membership.Role.COMMERCIAL,
    )
    second = add_membership(
        organization_id=organization.pk,
        user_id=second_user.pk,
        role=Membership.Role.FINANCE,
    )

    results = _run_serialized_pair(
        lambda: change_membership_role(
            organization_id=organization.pk,
            membership_id=first.pk,
            target_role=Membership.Role.OWNER,
        ),
        lambda: change_membership_role(
            organization_id=organization.pk,
            membership_id=second.pk,
            target_role=Membership.Role.OWNER,
        ),
    )

    assert [status for status, _ in results] == ["ok", "ok"]
    assert (
        Membership.objects.filter(
            organization=organization,
            role=Membership.Role.OWNER,
            status=Membership.Status.ACTIVE,
        ).count()
        == 3
    )


def test_operations_on_different_organizations_do_not_share_the_lock() -> None:
    first_org, _, first_target = _two_owner_organization("different-first")
    second_org, _, second_target = _two_owner_organization("different-second")
    barrier = Barrier(3)
    both_completed: Queue[str] = Queue()
    allow_commit = Event()

    def worker(organization_id: Any, membership_id: Any) -> str:
        close_old_connections()
        database = connections["default"]
        try:
            with transaction.atomic():
                barrier.wait(timeout=5)
                change_membership_role(
                    organization_id=organization_id,
                    membership_id=membership_id,
                    target_role=Membership.Role.ADMINISTRATOR,
                )
                both_completed.put("done")
                if not allow_commit.wait(timeout=5):
                    raise TimeoutError("La prueba no liberó el commit.")
            return "ok"
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(worker, first_org.pk, first_target.pk),
            executor.submit(worker, second_org.pk, second_target.pk),
        ]
        barrier.wait(timeout=5)
        try:
            assert both_completed.get(timeout=5) == "done"
            assert both_completed.get(timeout=5) == "done"
        finally:
            allow_commit.set()
        assert [future.result(timeout=5) for future in futures] == ["ok", "ok"]


def test_rollback_releases_lock_and_competitor_rechecks_owner_count() -> None:
    organization, first_owner, second_owner = _two_owner_organization("rollback")
    changed = Event()
    allow_rollback = Event()
    second_started = Event()
    first_pid: Queue[int] = Queue()
    second_pid: Queue[int] = Queue()

    def rollback_worker() -> str:
        close_old_connections()
        database = connections["default"]
        try:
            with pytest.raises(RuntimeError, match="forced rollback"), transaction.atomic():
                with database.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    first_pid.put(cursor.fetchone()[0])
                change_membership_role(
                    organization_id=organization.pk,
                    membership_id=first_owner.pk,
                    target_role=Membership.Role.ADMINISTRATOR,
                )
                changed.set()
                if not allow_rollback.wait(timeout=5):
                    raise TimeoutError("La prueba no liberó el rollback.")
                raise RuntimeError("forced rollback")
            return "rolled_back"
        finally:
            database.close()

    def competing_worker() -> str:
        close_old_connections()
        database = connections["default"]
        try:
            with database.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                second_pid.put(cursor.fetchone()[0])
            second_started.set()
            change_membership_role(
                organization_id=organization.pk,
                membership_id=second_owner.pk,
                target_role=Membership.Role.ADMINISTRATOR,
            )
            return "committed"
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(rollback_worker)
        assert changed.wait(timeout=5)
        second_future = executor.submit(competing_worker)
        assert second_started.wait(timeout=5)
        pids = [first_pid.get(timeout=5), second_pid.get(timeout=5)]
        try:
            _observe_waiting_lock(pids)
        finally:
            allow_rollback.set()
        assert first_future.result(timeout=5) == "rolled_back"
        assert second_future.result(timeout=5) == "committed"

    first_owner.refresh_from_db()
    second_owner.refresh_from_db()
    assert first_owner.role == Membership.Role.OWNER
    assert second_owner.role == Membership.Role.ADMINISTRATOR


def test_bootstrap_advisory_lock_makes_same_target_idempotent() -> None:
    barrier = Barrier(3)
    backend_pids: Queue[int] = Queue()
    first_completed = Event()
    allow_commit = Event()

    def bootstrap() -> Any:
        return bootstrap_organization(
            email="concurrent-bootstrap@example.com",
            display_name="Concurrent Owner",
            password=PASSWORD,
            organization_name="Concurrent Bootstrap",
            organization_slug="concurrent-bootstrap",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _serialized_worker,
                barrier=barrier,
                backend_pids=backend_pids,
                first_completed=first_completed,
                allow_commit=allow_commit,
                operation=bootstrap,
            )
            for _ in range(2)
        ]
        pids = [backend_pids.get(timeout=5), backend_pids.get(timeout=5)]
        barrier.wait(timeout=5)
        try:
            assert first_completed.wait(timeout=5)
            _observe_waiting_lock(pids)
        finally:
            allow_commit.set()
        results = [future.result(timeout=5) for future in futures]

    assert [status for status, _ in results] == ["ok", "ok"]
    assert sorted(result.created for _, result in results) == [False, True]
    assert Organization.objects.filter(slug="concurrent-bootstrap").count() == 1
    assert Membership.objects.filter(organization__slug="concurrent-bootstrap").count() == 1
