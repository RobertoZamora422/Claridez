"""Evidencia source-owned prospectiva P15; no backfill de estados históricos."""

from django.db import migrations, models

SQL = r"""
CREATE FUNCTION public.resources_capture_metric_state() RETURNS trigger
LANGUAGE plpgsql AS $function$
DECLARE
    snapshot jsonb;
    source_revision bigint;
    now_at timestamptz := clock_timestamp();
    base_unit uuid;
BEGIN
    SELECT base_unit_id INTO STRICT base_unit FROM public.resources_resource
    WHERE organization_id = NEW.organization_id AND id = NEW.resource_id;
    SELECT COALESCE(MAX((payload->>'source_revision')::bigint), 0) + 1
    INTO source_revision FROM public.resources_resourceevent
    WHERE organization_id = NEW.organization_id AND aggregate_kind = TG_TABLE_NAME
      AND aggregate_id = NEW.id AND kind = 'analytics_state_recorded';
    snapshot := jsonb_build_object(
        'source_version', 1, 'source_revision', source_revision,
        'resource_id', NEW.resource_id, 'unit_id', base_unit, 'quantity', NEW.quantity
    );
    IF TG_TABLE_NAME = 'resources_resourceunavailability' THEN
        snapshot := snapshot || jsonb_build_object(
            'location_id', NEW.location_id, 'is_active', NEW.is_active,
            'starts_at', lower(NEW.unavailable_interval),
            'ends_at', upper(NEW.unavailable_interval), 'corrects_id', NEW.corrects_id
        );
    ELSE
        snapshot := snapshot || jsonb_build_object(
            'root_reservation_id', NEW.root_reservation_id, 'reservation_id', NEW.reservation_id,
            'starts_at', lower(NEW.resource_interval), 'ends_at', upper(NEW.resource_interval),
            'status', NEW.status
        );
        IF TG_TABLE_NAME = 'resources_resourcerequirement' THEN
            snapshot := snapshot || jsonb_build_object(
                'temporal_source', NEW.temporal_source,
                'predecessor_id', NEW.predecessor_requirement_id
            );
        ELSE
            snapshot := snapshot || jsonb_build_object(
                'requirement_id', NEW.requirement_id, 'source_location_id', NEW.source_location_id,
                'predecessor_id', NEW.predecessor_assignment_id
            );
        END IF;
    END IF;
    INSERT INTO public.resources_resourceevent (
        id, organization_id, created_at, aggregate_kind, aggregate_id, kind,
        payload, occurred_at, recorded_by_membership_id
    ) VALUES (
        gen_random_uuid(), NEW.organization_id, now_at, TG_TABLE_NAME, NEW.id,
        'analytics_state_recorded', snapshot, now_at, NULL
    );
    RETURN NEW;
END;
$function$;
CREATE TRIGGER resources_requirement_metric_state
AFTER INSERT OR UPDATE ON public.resources_resourcerequirement
FOR EACH ROW EXECUTE FUNCTION public.resources_capture_metric_state();
CREATE TRIGGER resources_assignment_metric_state
AFTER INSERT OR UPDATE ON public.resources_resourceassignment
FOR EACH ROW EXECUTE FUNCTION public.resources_capture_metric_state();
CREATE TRIGGER resources_unavailability_metric_state
AFTER INSERT OR UPDATE ON public.resources_resourceunavailability
FOR EACH ROW EXECUTE FUNCTION public.resources_capture_metric_state();
"""


class Migration(migrations.Migration):
    dependencies = [("resources", "0006_preserve_custody_interval_guard")]
    operations = [
        migrations.AddIndex(
            model_name="resourceevent",
            index=models.Index(
                fields=["organization", "aggregate_kind", "aggregate_id", "created_at"],
                name="resources_metric_history_idx",
            ),
        ),
        migrations.RunSQL(
            SQL,
            """
            DROP TRIGGER resources_requirement_metric_state ON public.resources_resourcerequirement;
            DROP TRIGGER resources_assignment_metric_state ON public.resources_resourceassignment;
            DROP TRIGGER resources_unavailability_metric_state
                ON public.resources_resourceunavailability;
            DROP FUNCTION public.resources_capture_metric_state();
        """,
        ),
    ]
