from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_guard_commercial_operations()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    previous_context text;
    current_status text;
    current_confirmation_source uuid;
    preparation_status text;
    successor_id uuid;
    successor_status text;
    successor_preparation_status text;
    baseline_count integer;
    initialized_count integer;
    terminal_transition_count integer;
BEGIN
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', NEW.organization_id::text, true);
    BEGIN
        SELECT status, confirmation_source_id
        INTO current_status, current_confirmation_source
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND id = NEW.id;
        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
        SELECT status INTO preparation_status
        FROM public.operations_eventpreparation
        WHERE organization_id = NEW.organization_id AND reservation_id = NEW.id;
        SELECT count(*) FILTER (WHERE baseline_key IS NOT NULL)
        INTO baseline_count
        FROM public.operations_preparationitem
        WHERE organization_id = NEW.organization_id AND preparation_id = NEW.id;
        SELECT count(*) FILTER (WHERE cause = 'initialized'),
               count(*) FILTER (
                   WHERE cause IN ('commercial_cancellation', 'schedule_reschedule')
               )
        INTO initialized_count, terminal_transition_count
        FROM public.operations_preparationtransition
        WHERE organization_id = NEW.organization_id AND preparation_id = NEW.id;

        IF current_status = 'confirmed' THEN
            IF preparation_status NOT IN ('preparing', 'ready', 'in_progress', 'completed')
               OR baseline_count <> 7 OR initialized_count <> 1 THEN
                RAISE EXCEPTION 'confirmed reservation requires complete operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_status = 'cancelled' AND current_confirmation_source IS NOT NULL THEN
            IF preparation_status <> 'cancelled' OR baseline_count <> 7
               OR initialized_count <> 1 OR terminal_transition_count <> 1 THEN
                RAISE EXCEPTION 'confirmed cancellation requires cancelled operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_status = 'rescheduled' THEN
            SELECT id, status INTO successor_id, successor_status
            FROM public.commercial_reservation
            WHERE organization_id = NEW.organization_id AND predecessor_id = NEW.id;
            SELECT status INTO successor_preparation_status
            FROM public.operations_eventpreparation
            WHERE organization_id = NEW.organization_id AND reservation_id = successor_id;
            IF current_confirmation_source IS NOT NULL THEN
                IF preparation_status <> 'rescheduled'
                   OR successor_status <> 'confirmed'
                   OR successor_preparation_status <> 'preparing'
                   OR terminal_transition_count <> 1 THEN
                    RAISE EXCEPTION
                        'confirmed reschedule requires replacement operation aggregate'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF preparation_status IS NOT NULL
               OR successor_preparation_status IS NOT NULL THEN
                RAISE EXCEPTION 'provisional reschedule cannot create operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_confirmation_source IS NULL AND preparation_status IS NOT NULL THEN
            RAISE EXCEPTION 'unconfirmed reservation cannot have operation aggregate'
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
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_commercial_operations() FROM PUBLIC;
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0002_integrity_cutover_and_rls")]

    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
