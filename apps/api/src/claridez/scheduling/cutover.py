from __future__ import annotations

from typing import Any

from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder


class CutoverIntegrityError(RuntimeError):
    pass


def _scalar(cursor: Any, statement: str, parameters: tuple[Any, ...] = ()) -> int:
    cursor.execute(statement, parameters)
    return int(cursor.fetchone()[0])


def verify_scheduling_cutover() -> dict[str, Any]:
    """Verifica el cutover P8 sin alterar estado ni exponer datos de negocio."""
    migration_name = "0009_allow_terminal_operational_successors"
    if (
        not MigrationRecorder(connection)
        .migration_qs.filter(app="scheduling", name=migration_name)
        .exists()
    ):
        raise CutoverIntegrityError("La cabeza de migraciones de scheduling no está aplicada.")

    checked_reservations = 0
    checked_blocks = 0
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        previous_context = cursor.fetchone()[0] or ""
        cursor.execute("SELECT id FROM public.organizations_organization ORDER BY id")
        organization_ids = [row[0] for row in cursor.fetchall()]
        try:
            for organization_id in organization_ids:
                cursor.execute(
                    "SELECT set_config('claridez.organization_id', %s, true)",
                    (str(organization_id),),
                )
                invalid_reservations = _scalar(
                    cursor,
                    r"""
                    SELECT count(*)
                    FROM public.commercial_reservation AS reservation
                    LEFT JOIN public.commercial_quotationversion AS version
                      ON version.organization_id = reservation.organization_id
                     AND version.id = reservation.quotation_version_id
                    LEFT JOIN public.commercial_quotation AS quotation
                      ON quotation.organization_id = version.organization_id
                     AND quotation.id = version.quotation_id
                    LEFT JOIN public.scheduling_scheduleallocation AS allocation
                      ON allocation.organization_id = reservation.organization_id
                     AND allocation.reservation_id = reservation.id
                    LEFT JOIN public.scheduling_scheduleevent AS source_event
                      ON source_event.organization_id = allocation.organization_id
                     AND source_event.id = allocation.source_event_id
                    WHERE reservation.organization_id = %s AND (
                        reservation.root_id IS NULL
                        OR isempty(reservation.event_interval)
                        OR lower_inf(reservation.event_interval)
                        OR upper_inf(reservation.event_interval)
                        OR NOT lower_inc(reservation.event_interval)
                        OR upper_inc(reservation.event_interval)
                        OR lower(reservation.event_interval) >= upper(reservation.event_interval)
                        OR reservation.event_timezone = ''
                        OR reservation.setup_minutes < 0 OR reservation.teardown_minutes < 0
                        OR reservation.buffer_before_minutes < 0
                        OR reservation.buffer_after_minutes < 0
                        OR version.id IS NULL OR version.status <> 'accepted'
                        OR quotation.event_request_id <> reservation.event_request_id
                        OR allocation.id IS NULL
                        OR allocation.space_id <> reservation.space_id
                        OR allocation.source_revision <> reservation.revision
                        OR allocation.occupied_interval IS DISTINCT FROM tstzrange(
                            lower(reservation.event_interval)
                                - make_interval(mins => reservation.setup_minutes
                                    + reservation.buffer_before_minutes),
                            upper(reservation.event_interval)
                                + make_interval(mins => reservation.teardown_minutes
                                    + reservation.buffer_after_minutes), '[)')
                        OR allocation.is_blocking IS DISTINCT FROM
                            (reservation.status IN ('provisional', 'confirmed'))
                        OR source_event.id IS NULL
                    )
                    """,
                    (organization_id,),
                )
                invalid_chains = _scalar(
                    cursor,
                    r"""
                    WITH RECURSIVE ancestry AS (
                        SELECT id AS origin, id, predecessor_id, ARRAY[id] AS path, false AS cycle
                        FROM public.commercial_reservation
                        WHERE organization_id = %s
                        UNION ALL
                        SELECT ancestry.origin, predecessor.id, predecessor.predecessor_id,
                               ancestry.path || predecessor.id,
                               predecessor.id = ANY(ancestry.path)
                        FROM ancestry
                        JOIN public.commercial_reservation AS predecessor
                          ON predecessor.organization_id = %s
                         AND predecessor.id = ancestry.predecessor_id
                        WHERE NOT ancestry.cycle
                    )
                    SELECT count(*) FROM ancestry WHERE cycle
                    """,
                    (organization_id, organization_id),
                )
                invalid_reschedules = _scalar(
                    cursor,
                    r"""
                    SELECT count(*)
                    FROM public.commercial_reservation AS predecessor
                    LEFT JOIN public.commercial_reservation AS successor
                      ON successor.organization_id = predecessor.organization_id
                     AND successor.predecessor_id = predecessor.id
                    WHERE predecessor.organization_id = %s
                      AND predecessor.status = 'rescheduled'
                      AND (
                        successor.id IS NULL
                        OR successor.root_id <> predecessor.root_id
                        OR successor.event_request_id <> predecessor.event_request_id
                        OR successor.quotation_version_id <> predecessor.quotation_version_id
                        OR NOT EXISTS (
                            SELECT 1 FROM public.scheduling_scheduleevent AS event
                            WHERE event.organization_id = predecessor.organization_id
                              AND event.kind = 'reservation_rescheduled'
                              AND event.predecessor_id = predecessor.id
                              AND event.successor_id = successor.id
                        )
                      )
                    """,
                    (organization_id,),
                )
                invalid_blocks = _scalar(
                    cursor,
                    r"""
                    SELECT count(*)
                    FROM public.scheduling_scheduleblocktarget AS target
                    JOIN public.scheduling_scheduleblock AS block
                      ON block.organization_id = target.organization_id
                     AND block.id = target.block_id
                    LEFT JOIN public.scheduling_scheduleallocation AS allocation
                      ON allocation.organization_id = target.organization_id
                     AND allocation.block_target_id = target.id
                    WHERE target.organization_id = %s AND (
                        allocation.id IS NULL
                        OR allocation.space_id <> target.space_id
                        OR allocation.occupied_interval IS DISTINCT FROM block.blocked_interval
                        OR allocation.source_revision <> block.revision
                        OR allocation.is_blocking IS DISTINCT FROM (block.status = 'active')
                    )
                    """,
                    (organization_id,),
                )
                overdue_holds = _scalar(
                    cursor,
                    """
                    SELECT count(*) FROM public.commercial_reservation
                    WHERE organization_id = %s AND status = 'provisional'
                      AND hold_expires_at <= transaction_timestamp()
                    """,
                    (organization_id,),
                )
                if any(
                    (
                        invalid_reservations,
                        invalid_chains,
                        invalid_reschedules,
                        invalid_blocks,
                        overdue_holds,
                    )
                ):
                    raise CutoverIntegrityError(
                        "La equivalencia, cadena o expiración posterior al cutover P8 falló."
                    )
                checked_reservations += _scalar(
                    cursor,
                    "SELECT count(*) FROM public.commercial_reservation WHERE organization_id = %s",
                    (organization_id,),
                )
                checked_blocks += _scalar(
                    cursor,
                    "SELECT count(*) FROM public.scheduling_scheduleblock "
                    "WHERE organization_id = %s",
                    (organization_id,),
                )
        finally:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, true)",
                (previous_context,),
            )

        cursor.execute(
            """
            SELECT count(*) FILTER (WHERE relrowsecurity AND relforcerowsecurity), count(*)
            FROM pg_class
            WHERE relname IN (
                'scheduling_spaceschedulepolicy', 'scheduling_scheduleblock',
                'scheduling_scheduleblocktarget', 'scheduling_scheduleevent',
                'scheduling_scheduleallocation'
            )
            """
        )
        protected, table_count = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                count(*) FILTER (WHERE conname = 'scheduling_allocation_no_overlap'),
                count(*) FILTER (WHERE conname = 'commercial_reservation_no_overlap')
            FROM pg_constraint
            WHERE contype = 'x'
            """
        )
        scheduling_exclusions, legacy_exclusions = cursor.fetchone()
        cursor.execute(
            """
            SELECT count(*) FROM pg_trigger
            WHERE NOT tgisinternal AND tgenabled <> 'D' AND tgname IN (
                'scheduling_reservation_integrity_guard',
                'scheduling_allocation_integrity_guard',
                'scheduling_event_immutable',
                'scheduling_allocation_expire_due'
            )
            """
        )
        guardian_count = cursor.fetchone()[0]
    if (protected, table_count) != (5, 5):
        raise CutoverIntegrityError("RLS/FORCE RLS de scheduling no está completo.")
    if (scheduling_exclusions, legacy_exclusions) != (1, 0):
        raise CutoverIntegrityError("La exclusión temporal única de P8 no está instalada.")
    if guardian_count != 4:
        raise CutoverIntegrityError("Los guardianes PostgreSQL esenciales de P8 no están activos.")
    return {
        "status": "ok",
        "scheduling_migration": migration_name,
        "organizations_checked": len(organization_ids),
        "reservations_checked": checked_reservations,
        "blocks_checked": checked_blocks,
    }
