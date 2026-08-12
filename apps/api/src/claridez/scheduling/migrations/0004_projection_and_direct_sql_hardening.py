from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.claridez_guard_schedule_policy()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'schedule policies cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.revision <> 1 THEN
            RAISE EXCEPTION 'schedule policy must start at revision one'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.organization_id <> OLD.organization_id OR NEW.space_id <> OLD.space_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'invalid schedule policy revision' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_schedule_policy() FROM PUBLIC;
CREATE TRIGGER scheduling_policy_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_spaceschedulepolicy
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_schedule_policy();

CREATE FUNCTION public.claridez_guard_schedule_block()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'active' OR NEW.revision <> 1 THEN
            RAISE EXCEPTION 'schedule block must start active at revision one'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF OLD.status IN ('released', 'cancelled') THEN
            RAISE EXCEPTION 'terminal schedule blocks are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.organization_id <> OLD.organization_id OR NEW.venue_id <> OLD.venue_id
           OR NEW.scope <> OLD.scope OR NEW.blocked_interval <> OLD.blocked_interval
           OR NEW.event_timezone <> OLD.event_timezone OR NEW.reason <> OLD.reason
           OR NEW.created_by_membership_id <> OLD.created_by_membership_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.status NOT IN ('released', 'cancelled')
           OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'invalid schedule block transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_schedule_block() FROM PUBLIC;
CREATE TRIGGER scheduling_block_guard
BEFORE INSERT OR UPDATE ON public.scheduling_scheduleblock
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_schedule_block();

CREATE OR REPLACE FUNCTION public.claridez_guard_carried_preparation_item()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    source_item record;
    destination_exists boolean;
BEGIN
    IF NEW.carried_from_item_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.baseline_key IS NOT NULL OR NEW.status <> 'pending'
       OR NEW.due_on IS NOT NULL OR NEW.resolved_at IS NOT NULL
       OR NEW.resolved_by_membership_id IS NOT NULL OR NEW.status_note <> ''
       OR NEW.revision <> 1 THEN
        RAISE EXCEPTION 'carried free item must restart as pending'
            USING ERRCODE = '23514';
    END IF;
    SELECT item.*, preparation.status AS preparation_status,
           preparation.rescheduled_to_reservation_id
    INTO source_item
    FROM public.operations_preparationitem AS item
    JOIN public.operations_eventpreparation AS preparation
      ON preparation.organization_id = item.organization_id
     AND preparation.reservation_id = item.preparation_id
    WHERE item.organization_id = NEW.organization_id
      AND item.id = NEW.carried_from_item_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'carried item source does not exist' USING ERRCODE = '23514';
    END IF;
    SELECT EXISTS (
        SELECT 1 FROM public.operations_eventpreparation
        WHERE organization_id = NEW.organization_id
          AND reservation_id = NEW.preparation_id
    ) INTO destination_exists;
    IF NOT destination_exists OR source_item.baseline_key IS NOT NULL
       OR source_item.preparation_status <> 'rescheduled'
       OR source_item.rescheduled_to_reservation_id <> NEW.preparation_id
       OR ROW(NEW.title, NEW.section, NEW.is_required, NEW.notes)
          IS DISTINCT FROM ROW(
              source_item.title, source_item.section,
              source_item.is_required, source_item.notes
          ) THEN
        RAISE EXCEPTION 'carried item provenance is invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_carried_preparation_item() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_validate_scheduling_integrity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_organization uuid;
    previous_context text;
BEGIN
    target_organization := coalesce(NEW.organization_id, OLD.organization_id);
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', target_organization::text, true
    );
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM public.commercial_reservation AS reservation
            LEFT JOIN public.scheduling_scheduleallocation AS allocation
              ON allocation.organization_id = reservation.organization_id
             AND allocation.reservation_id = reservation.id
            LEFT JOIN public.scheduling_scheduleevent AS source_event
              ON source_event.organization_id = allocation.organization_id
             AND source_event.id = allocation.source_event_id
            WHERE reservation.organization_id = target_organization
              AND (
                  allocation.id IS NULL
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
                  OR source_event.event_request_id <> reservation.event_request_id
                  OR source_event.root_reservation_id <> reservation.root_id
                  OR NOT (
                      (source_event.kind = 'cutover_snapshot'
                          AND source_event.reservation_id = reservation.id)
                      OR (source_event.kind = 'reservation_hold_created'
                          AND reservation.status = 'provisional'
                          AND source_event.reservation_id = reservation.id
                          AND source_event.aggregate_revision = reservation.revision)
                      OR (source_event.kind = 'reservation_confirmed'
                          AND reservation.status = 'confirmed'
                          AND source_event.reservation_id = reservation.id
                          AND source_event.aggregate_revision = reservation.revision)
                      OR (source_event.kind = 'reservation_expired'
                          AND reservation.status = 'expired'
                          AND source_event.reservation_id = reservation.id
                          AND source_event.aggregate_revision = reservation.revision)
                      OR (source_event.kind = 'reservation_cancelled'
                          AND reservation.status = 'cancelled'
                          AND source_event.reservation_id = reservation.id
                          AND source_event.aggregate_revision = reservation.revision)
                      OR (source_event.kind = 'reservation_rescheduled'
                          AND (
                              (reservation.status = 'rescheduled'
                                  AND source_event.predecessor_id = reservation.id
                                  AND source_event.aggregate_revision = reservation.revision)
                              OR (reservation.status IN ('provisional', 'confirmed')
                                  AND source_event.successor_id = reservation.id
                                  AND (source_event.new_snapshot ->> 'revision')::integer
                                      = reservation.revision)
                          ))
                  )
              )
        ) THEN
            RAISE EXCEPTION 'reservation allocation diverges from scheduling authority'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM public.commercial_reservation AS predecessor
            LEFT JOIN public.commercial_reservation AS successor
              ON successor.organization_id = predecessor.organization_id
             AND successor.predecessor_id = predecessor.id
            WHERE predecessor.organization_id = target_organization
              AND predecessor.status = 'rescheduled'
              AND (
                  successor.id IS NULL
                  OR successor.root_id <> predecessor.root_id
                  OR successor.event_request_id <> predecessor.event_request_id
                  OR successor.quotation_version_id <> predecessor.quotation_version_id
                  OR successor.status NOT IN ('provisional', 'confirmed')
                  OR NOT EXISTS (
                      SELECT 1 FROM public.scheduling_scheduleevent AS event
                      WHERE event.organization_id = predecessor.organization_id
                        AND event.kind = 'reservation_rescheduled'
                        AND event.predecessor_id = predecessor.id
                        AND event.successor_id = successor.id
                        AND event.root_reservation_id = predecessor.root_id
                  )
              )
        ) THEN
            RAISE EXCEPTION 'rescheduled reservation requires one coherent successor and event'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            WITH RECURSIVE ancestry AS (
                SELECT id AS origin, id, predecessor_id, ARRAY[id] AS path, false AS cycle
                FROM public.commercial_reservation
                WHERE organization_id = target_organization
                UNION ALL
                SELECT ancestry.origin, predecessor.id, predecessor.predecessor_id,
                       ancestry.path || predecessor.id,
                       predecessor.id = ANY(ancestry.path)
                FROM ancestry
                JOIN public.commercial_reservation AS predecessor
                  ON predecessor.organization_id = target_organization
                 AND predecessor.id = ancestry.predecessor_id
                WHERE NOT ancestry.cycle
            )
            SELECT 1 FROM ancestry WHERE cycle
        ) THEN
            RAISE EXCEPTION 'reservation chain contains a cycle' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM public.scheduling_scheduleblocktarget AS target
            JOIN public.scheduling_scheduleblock AS block
              ON block.organization_id = target.organization_id AND block.id = target.block_id
            LEFT JOIN public.scheduling_scheduleallocation AS allocation
              ON allocation.organization_id = target.organization_id
             AND allocation.block_target_id = target.id
            LEFT JOIN public.scheduling_scheduleevent AS source_event
              ON source_event.organization_id = allocation.organization_id
             AND source_event.id = allocation.source_event_id
            WHERE target.organization_id = target_organization
              AND (
                  allocation.id IS NULL OR allocation.space_id <> target.space_id
                  OR allocation.occupied_interval IS DISTINCT FROM block.blocked_interval
                  OR allocation.source_revision <> block.revision
                  OR allocation.is_blocking IS DISTINCT FROM (block.status = 'active')
                  OR source_event.block_id <> block.id
                  OR source_event.aggregate_revision <> block.revision
                  OR source_event.kind IS DISTINCT FROM CASE block.status
                      WHEN 'active' THEN 'block_created'
                      WHEN 'released' THEN 'block_released'
                      ELSE 'block_cancelled'
                  END
              )
        ) THEN
            RAISE EXCEPTION 'block allocation diverges from scheduling authority'
                USING ERRCODE = '23514';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', coalesce(previous_context, ''), true
        );
        RAISE;
    END;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_scheduling_integrity() FROM PUBLIC;

CREATE FUNCTION public.claridez_guard_venue_block_space_coverage()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    previous_context text;
BEGIN
    IF NOT NEW.is_active THEN
        RETURN NULL;
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', NEW.organization_id::text, true);
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM public.scheduling_scheduleblock AS block
            WHERE block.organization_id = NEW.organization_id
              AND block.venue_id = NEW.venue_id
              AND block.scope = 'venue' AND block.status = 'active'
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.scheduling_scheduleblocktarget AS target
                  JOIN public.scheduling_scheduleallocation AS allocation
                    ON allocation.organization_id = target.organization_id
                   AND allocation.block_target_id = target.id
                  WHERE target.organization_id = block.organization_id
                    AND target.block_id = block.id AND target.space_id = NEW.id
                    AND allocation.space_id = NEW.id
                    AND allocation.occupied_interval = block.blocked_interval
                    AND allocation.is_blocking
              )
        ) THEN
            RAISE EXCEPTION 'active venue block must cover every active space'
                USING ERRCODE = '23514';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', coalesce(previous_context, ''), true
        );
        RAISE;
    END;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_venue_block_space_coverage() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER scheduling_venue_block_space_coverage
AFTER INSERT OR UPDATE OF is_active, venue_id ON public.organizations_space
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_venue_block_space_coverage();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS scheduling_venue_block_space_coverage
    ON public.organizations_space;
DROP FUNCTION IF EXISTS public.claridez_guard_venue_block_space_coverage();
DROP TRIGGER IF EXISTS scheduling_block_guard ON public.scheduling_scheduleblock;
DROP FUNCTION IF EXISTS public.claridez_guard_schedule_block();
DROP TRIGGER IF EXISTS scheduling_policy_guard ON public.scheduling_spaceschedulepolicy;
DROP FUNCTION IF EXISTS public.claridez_guard_schedule_policy();
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0003_current_state_operations_guardian")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
