from django.db import migrations

GUARDIAN_FORWARD = r"""
CREATE FUNCTION public.claridez_guard_commercial_operations()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    previous_context text;
    preparation_status text;
    baseline_count integer;
    expected_baseline_count integer;
    initialized_count integer;
    cancellation_count integer;
    current_reservation_status text;
    current_confirmed_at timestamptz;
BEGIN
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', NEW.organization_id::text, true);
    BEGIN
        SELECT status, confirmed_at
        INTO current_reservation_status, current_confirmed_at
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND id = NEW.id;
        SELECT status INTO preparation_status
        FROM public.operations_eventpreparation
        WHERE organization_id = NEW.organization_id AND reservation_id = NEW.id;

        SELECT
            count(*) FILTER (WHERE baseline_key IS NOT NULL),
            count(*) FILTER (WHERE baseline_key IN (
                'space_layout', 'guest_count', 'special_requirements', 'entry_schedule',
                'furniture', 'decoration', 'final_readiness_review'
            ))
        INTO baseline_count, expected_baseline_count
        FROM public.operations_preparationitem
        WHERE organization_id = NEW.organization_id
          AND preparation_id = NEW.id;
        SELECT count(*) INTO initialized_count
        FROM public.operations_preparationtransition
        WHERE organization_id = NEW.organization_id
          AND preparation_id = NEW.id AND cause = 'initialized';
        SELECT count(*) INTO cancellation_count
        FROM public.operations_preparationtransition
        WHERE organization_id = NEW.organization_id
          AND preparation_id = NEW.id AND cause = 'commercial_cancellation';

        IF current_reservation_status = 'confirmed' THEN
            IF preparation_status IS NULL OR preparation_status = 'cancelled'
               OR baseline_count <> 7 OR expected_baseline_count <> 7
               OR initialized_count <> 1 THEN
                RAISE EXCEPTION 'confirmed reservation requires complete operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_reservation_status = 'cancelled' AND current_confirmed_at IS NOT NULL THEN
            IF preparation_status IS DISTINCT FROM 'cancelled'
               OR baseline_count <> 7 OR expected_baseline_count <> 7
               OR initialized_count <> 1 OR cancellation_count <> 1 THEN
                RAISE EXCEPTION 'commercial cancellation requires cancelled operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_confirmed_at IS NULL
              OR current_reservation_status IN ('provisional', 'expired') THEN
            IF preparation_status IS NOT NULL THEN
                RAISE EXCEPTION 'unconfirmed reservation cannot have operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
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
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_guard_commercial_operations() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER commercial_operations_guardian
AFTER INSERT OR UPDATE ON public.commercial_reservation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_commercial_operations();
"""

GUARDIAN_REVERSE = r"""
DROP TRIGGER IF EXISTS commercial_operations_guardian ON public.commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_guard_commercial_operations();
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]

    operations = [migrations.RunSQL(GUARDIAN_FORWARD, GUARDIAN_REVERSE)]
