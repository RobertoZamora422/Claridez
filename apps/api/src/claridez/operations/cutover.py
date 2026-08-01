from __future__ import annotations

from typing import Any

from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder


class CutoverIntegrityError(RuntimeError):
    pass


def verify_operations_cutover() -> dict[str, Any]:
    """Verifica el agregado 5.2 sin exponer datos personales."""
    if (
        not MigrationRecorder(connection)
        .migration_qs.filter(app="operations", name="0002_commercial_operations_guardian")
        .exists()
    ):
        raise CutoverIntegrityError("La cabeza de migraciones de operations no está aplicada.")

    checked_reservations = 0
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
                cursor.execute(
                    """
                    SELECT count(*)
                    FROM public.commercial_reservation AS reservation
                    LEFT JOIN public.operations_eventpreparation AS preparation
                      ON preparation.organization_id = reservation.organization_id
                     AND preparation.reservation_id = reservation.id
                    LEFT JOIN LATERAL (
                        SELECT
                            count(*) FILTER (WHERE baseline_key IS NOT NULL) AS total,
                            count(*) FILTER (WHERE baseline_key IN (
                                'space_layout', 'guest_count', 'special_requirements',
                                'entry_schedule', 'furniture', 'decoration',
                                'final_readiness_review'
                            )) AS expected
                        FROM public.operations_preparationitem AS item
                        WHERE item.organization_id = reservation.organization_id
                          AND item.preparation_id = reservation.id
                    ) AS baseline ON true
                    LEFT JOIN LATERAL (
                        SELECT
                            count(*) FILTER (WHERE cause = 'initialized') AS initialized,
                            count(*) FILTER (
                                WHERE cause = 'commercial_cancellation'
                            ) AS cancelled
                        FROM public.operations_preparationtransition AS transition
                        WHERE transition.organization_id = reservation.organization_id
                          AND transition.preparation_id = reservation.id
                    ) AS transitions ON true
                    WHERE reservation.organization_id = %s AND (
                        (reservation.status = 'confirmed' AND (
                            preparation.reservation_id IS NULL
                            OR preparation.status = 'cancelled'
                            OR baseline.total <> 7 OR baseline.expected <> 7
                            OR transitions.initialized <> 1
                        ))
                        OR (reservation.status = 'cancelled'
                            AND reservation.confirmed_at IS NOT NULL AND (
                                preparation.status IS DISTINCT FROM 'cancelled'
                                OR baseline.total <> 7 OR baseline.expected <> 7
                                OR transitions.initialized <> 1
                                OR transitions.cancelled <> 1
                            ))
                        OR ((reservation.confirmed_at IS NULL
                            OR reservation.status IN ('provisional', 'expired'))
                            AND preparation.reservation_id IS NOT NULL)
                    )
                    """,
                    (organization_id,),
                )
                if cursor.fetchone()[0]:
                    raise CutoverIntegrityError(
                        "La cardinalidad o integridad operativa posterior al backfill falló."
                    )
                cursor.execute(
                    "SELECT count(*) FROM public.commercial_reservation WHERE organization_id = %s",
                    (organization_id,),
                )
                checked_reservations += cursor.fetchone()[0]
        finally:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, true)",
                (previous_context,),
            )
        cursor.execute(
            """
            SELECT
                count(*) FILTER (WHERE relrowsecurity AND relforcerowsecurity),
                count(*)
            FROM pg_class
            WHERE relname IN (
                'operations_eventpreparation',
                'operations_preparationitem',
                'operations_preparationtransition'
            )
            """
        )
        protected, total = cursor.fetchone()
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_trigger
            WHERE tgrelid = 'public.commercial_reservation'::regclass
              AND tgname = 'commercial_operations_guardian' AND tgenabled <> 'D'
            """
        )
        guardian_count = cursor.fetchone()[0]
    if (protected, total, guardian_count) != (3, 3, 1):
        raise CutoverIntegrityError("Las defensas PostgreSQL 5.2 no están completas.")
    return {
        "status": "ok",
        "operations_migration": "0002_commercial_operations_guardian",
        "organizations_checked": len(organization_ids),
        "reservations_checked": checked_reservations,
    }
