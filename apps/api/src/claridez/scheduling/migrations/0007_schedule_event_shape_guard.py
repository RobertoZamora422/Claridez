from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.claridez_guard_schedule_event_shape()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    reservation_request uuid;
    reservation_root uuid;
    block_organization uuid;
BEGIN
    IF NEW.source = 'user' AND NEW.actor_membership_id IS NULL THEN
        RAISE EXCEPTION 'user schedule event requires actor' USING ERRCODE = '23514';
    ELSIF NEW.source IN ('database_expiration', 'cutover')
          AND NEW.actor_membership_id IS NOT NULL THEN
        RAISE EXCEPTION 'system schedule event cannot claim actor' USING ERRCODE = '23514';
    END IF;

    IF NEW.kind IN (
        'reservation_hold_created', 'reservation_confirmed',
        'reservation_expired', 'reservation_cancelled'
    ) THEN
        IF NEW.event_request_id IS NULL OR NEW.root_reservation_id IS NULL
           OR NEW.reservation_id IS NULL OR NEW.predecessor_id IS NOT NULL
           OR NEW.successor_id IS NOT NULL OR NEW.block_id IS NOT NULL THEN
            RAISE EXCEPTION 'reservation schedule event has invalid shape'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'reservation_expired' THEN
            IF NEW.source <> 'database_expiration' OR NEW.actor_membership_id IS NOT NULL THEN
                RAISE EXCEPTION 'reservation expiration requires database authority'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.source <> 'user' THEN
            RAISE EXCEPTION 'interactive reservation event requires user authority'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.kind IN ('reservation_cancelled') AND btrim(NEW.reason) = '' THEN
            RAISE EXCEPTION 'reservation cancellation requires reason' USING ERRCODE = '23514';
        END IF;
        SELECT event_request_id, root_id INTO reservation_request, reservation_root
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id;
        IF reservation_request IS DISTINCT FROM NEW.event_request_id
           OR reservation_root IS DISTINCT FROM NEW.root_reservation_id THEN
            RAISE EXCEPTION 'reservation schedule event does not match reservation'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.kind = 'reservation_rescheduled' THEN
        IF NEW.source <> 'user' OR NEW.actor_membership_id IS NULL
           OR NEW.event_request_id IS NULL OR NEW.root_reservation_id IS NULL
           OR NEW.predecessor_id IS NULL OR NEW.successor_id IS NULL
           OR NEW.reservation_id IS DISTINCT FROM NEW.successor_id
           OR NEW.block_id IS NOT NULL OR btrim(NEW.reason) = '' THEN
            RAISE EXCEPTION 'reservation reschedule event has invalid shape'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM public.commercial_reservation AS predecessor
            JOIN public.commercial_reservation AS successor
              ON successor.organization_id = predecessor.organization_id
             AND successor.predecessor_id = predecessor.id
            WHERE predecessor.organization_id = NEW.organization_id
              AND predecessor.id = NEW.predecessor_id
              AND successor.id = NEW.successor_id
              AND predecessor.root_id = NEW.root_reservation_id
              AND successor.root_id = NEW.root_reservation_id
              AND predecessor.event_request_id = NEW.event_request_id
              AND successor.event_request_id = NEW.event_request_id
        ) THEN
            RAISE EXCEPTION 'reservation reschedule event does not match chain'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.kind IN ('block_created', 'block_released', 'block_cancelled') THEN
        IF NEW.source <> 'user' OR NEW.actor_membership_id IS NULL
           OR NEW.block_id IS NULL OR NEW.event_request_id IS NOT NULL
           OR NEW.root_reservation_id IS NOT NULL OR NEW.reservation_id IS NOT NULL
           OR NEW.predecessor_id IS NOT NULL OR NEW.successor_id IS NOT NULL
           OR btrim(NEW.reason) = '' THEN
            RAISE EXCEPTION 'block schedule event has invalid shape' USING ERRCODE = '23514';
        END IF;
        SELECT organization_id INTO block_organization
        FROM public.scheduling_scheduleblock
        WHERE organization_id = NEW.organization_id AND id = NEW.block_id;
        IF block_organization IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'block schedule event does not match block'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.kind = 'cutover_snapshot' THEN
        IF NEW.source <> 'cutover' OR NEW.actor_membership_id IS NOT NULL
           OR ((NEW.reservation_id IS NULL) = (NEW.block_id IS NULL)) THEN
            RAISE EXCEPTION 'cutover schedule event has invalid shape' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown schedule event kind' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_schedule_event_shape() FROM PUBLIC;
CREATE TRIGGER scheduling_event_shape_guard
BEFORE INSERT ON public.scheduling_scheduleevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_schedule_event_shape();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS scheduling_event_shape_guard ON public.scheduling_scheduleevent;
DROP FUNCTION IF EXISTS public.claridez_guard_schedule_event_shape();
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0006_explicit_migration_and_test_privileges")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
