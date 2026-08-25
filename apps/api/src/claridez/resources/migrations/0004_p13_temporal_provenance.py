from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE public.resources_resourcerequirement
ADD CONSTRAINT res_requirement_operation_window_fk
FOREIGN KEY (organization_id, operational_window_id)
REFERENCES public.operations_operationalresourcewindow (organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION public.claridez_resources_guard_requirement_temporal_source()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE reservation record; op_window record;
BEGIN
    SELECT id, organization_id, root_id, event_interval INTO reservation
    FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id FOR UPDATE;
    IF reservation.id IS NULL OR NEW.root_reservation_id <> reservation.root_id THEN
        RAISE EXCEPTION 'resource requirement reservation provenance is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.temporal_source = 'scheduling_event_interval' THEN
        IF NEW.operational_window_id IS NOT NULL
           OR NEW.resource_interval <> reservation.event_interval THEN
            RAISE EXCEPTION 'legacy requirement must equal reservation event interval'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.temporal_source = 'operations_window' THEN
        SELECT * INTO op_window FROM public.operations_operationalresourcewindow
        WHERE organization_id = NEW.organization_id AND id = NEW.operational_window_id;
        IF op_window.id IS NULL OR op_window.reservation_id <> NEW.reservation_id
           OR op_window.root_reservation_id <> NEW.root_reservation_id
           OR op_window.resource_id <> NEW.resource_id OR op_window.quantity <> NEW.quantity
           OR op_window.required_interval <> NEW.resource_interval THEN
            RAISE EXCEPTION 'P13 requirement must equal its authorized operations window'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown resource temporal source' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND ROW(
       NEW.organization_id, NEW.root_reservation_id, NEW.reservation_id,
       NEW.resource_id, NEW.quantity, NEW.resource_interval, NEW.temporal_source,
       NEW.operational_window_id, NEW.predecessor_requirement_id,
       NEW.created_by_membership_id, NEW.created_at)
       IS DISTINCT FROM ROW(
       OLD.organization_id, OLD.root_reservation_id, OLD.reservation_id,
       OLD.resource_id, OLD.quantity, OLD.resource_interval, OLD.temporal_source,
       OLD.operational_window_id, OLD.predecessor_requirement_id,
       OLD.created_by_membership_id, OLD.created_at) THEN
        RAISE EXCEPTION 'resource requirement temporal provenance is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_resources_guard_requirement_temporal_source() FROM PUBLIC;
CREATE TRIGGER resources_requirement_temporal_source_guard
BEFORE INSERT OR UPDATE ON public.resources_resourcerequirement
FOR EACH ROW EXECUTE FUNCTION public.claridez_resources_guard_requirement_temporal_source();

CREATE OR REPLACE FUNCTION public.claridez_resources_guard_allocation()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE assignment record; requirement record; reservation record; op_window record;
        allocation_authority record; event_authority record; predecessor_authority record;
        resource record; asset record;
        available numeric(20,6); custody numeric(20,6); used numeric(20,6);
        unavailable numeric(20,6);
BEGIN
    IF NOT NEW.is_active THEN RETURN NEW; END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'resources:' || NEW.organization_id::text || ':resource:' || NEW.resource_id::text, 0
    ));
    SELECT * INTO assignment FROM public.resources_resourceassignment
    WHERE organization_id = NEW.organization_id AND id = NEW.assignment_id FOR UPDATE;
    SELECT * INTO requirement FROM public.resources_resourcerequirement
    WHERE organization_id = NEW.organization_id AND id = assignment.requirement_id FOR UPDATE;
    SELECT id, root_id, status, hold_expires_at, event_interval, revision, space_id,
           event_request_id, predecessor_id INTO reservation
    FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id FOR UPDATE;
    SELECT * INTO resource FROM public.resources_resource
    WHERE organization_id = NEW.organization_id AND id = NEW.resource_id FOR UPDATE;
    IF assignment.id IS NULL OR requirement.id IS NULL OR resource.id IS NULL
       OR assignment.reservation_id <> NEW.reservation_id
       OR assignment.root_reservation_id <> reservation.root_id
       OR assignment.resource_id <> NEW.resource_id
       OR assignment.quantity <> NEW.quantity
       OR requirement.reservation_id <> assignment.reservation_id
       OR requirement.root_reservation_id <> assignment.root_reservation_id
       OR requirement.resource_id <> assignment.resource_id
       OR requirement.quantity <> assignment.quantity
       OR requirement.resource_interval <> assignment.resource_interval
    THEN
        RAISE EXCEPTION 'resource allocation does not match requirement and assignment'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.basis = 'scheduling' THEN
        IF reservation.id IS NULL OR reservation.status NOT IN ('provisional', 'confirmed')
           OR (reservation.status = 'provisional'
               AND reservation.hold_expires_at <= transaction_timestamp())
           OR assignment.status <> 'reserved'
           OR assignment.resource_interval <> NEW.resource_interval THEN
            RAISE EXCEPTION 'resource allocation is not schedulable' USING ERRCODE = '23514';
        END IF;
        IF requirement.temporal_source = 'scheduling_event_interval' THEN
            IF requirement.operational_window_id IS NOT NULL
               OR NEW.resource_interval <> reservation.event_interval THEN
                RAISE EXCEPTION 'legacy allocation diverges from reservation event interval'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF requirement.temporal_source = 'operations_window' THEN
            SELECT * INTO op_window FROM public.operations_operationalresourcewindow
            WHERE organization_id = NEW.organization_id
              AND id = requirement.operational_window_id;
            SELECT * INTO allocation_authority FROM public.scheduling_scheduleallocation
            WHERE organization_id = NEW.organization_id
              AND id = op_window.schedule_allocation_id;
            SELECT * INTO event_authority FROM public.scheduling_scheduleevent
            WHERE organization_id = NEW.organization_id AND id = op_window.schedule_event_id;
            SELECT * INTO predecessor_authority FROM public.commercial_reservation
            WHERE organization_id = NEW.organization_id AND id = reservation.predecessor_id;
            IF op_window.id IS NULL OR op_window.reservation_id <> reservation.id
               OR op_window.root_reservation_id <> reservation.root_id
               OR op_window.resource_id <> NEW.resource_id OR op_window.quantity <> NEW.quantity
               OR op_window.required_interval <> NEW.resource_interval
               OR allocation_authority.id IS NULL
               OR allocation_authority.reservation_id <> reservation.id
               OR allocation_authority.space_id <> reservation.space_id
               OR allocation_authority.source_event_id <> event_authority.id
               OR allocation_authority.source_revision <> reservation.revision
               OR op_window.schedule_reservation_revision <> reservation.revision
               OR op_window.schedule_source_revision <> allocation_authority.source_revision
               OR event_authority.event_request_id <> reservation.event_request_id
               OR event_authority.root_reservation_id <> reservation.root_id
               OR NOT (
                  (event_authority.kind = 'reservation_confirmed'
                    AND event_authority.reservation_id = reservation.id
                    AND event_authority.aggregate_revision = reservation.revision)
                  OR (event_authority.kind = 'reservation_rescheduled'
                    AND event_authority.reservation_id = reservation.id
                    AND event_authority.successor_id = reservation.id
                    AND event_authority.predecessor_id = reservation.predecessor_id
                    AND predecessor_authority.id = reservation.predecessor_id
                    AND predecessor_authority.root_id = reservation.root_id
                    AND predecessor_authority.event_request_id = reservation.event_request_id
                    AND predecessor_authority.status = 'rescheduled'
                    AND event_authority.aggregate_revision = predecessor_authority.revision
                    AND (event_authority.new_snapshot ->> 'revision')::integer
                        = reservation.revision)
                  OR (event_authority.kind = 'cutover_snapshot'
                    AND event_authority.reservation_id = reservation.id
                    AND event_authority.aggregate_revision = reservation.revision)
               )
               OR NOT (NEW.resource_interval <@ allocation_authority.occupied_interval)
            THEN
                RAISE EXCEPTION 'P13 allocation diverges from operations and scheduling authority'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'unknown requirement temporal source' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.basis = 'custody' THEN
        IF assignment.status <> 'custody' OR NOT upper_inf(NEW.resource_interval) THEN
            RAISE EXCEPTION 'custody capacity projection is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown capacity allocation basis' USING ERRCODE = '23514';
    END IF;
    IF resource.nature = 'consumable' THEN
        IF NEW.basis <> 'scheduling' THEN
            RAISE EXCEPTION 'consumables cannot retain custody capacity' USING ERRCODE = '23514';
        END IF;
        SELECT coalesce(quantity, 0) INTO available FROM public.resources_stockbalance
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND location_id = assignment.source_location_id FOR UPDATE;
        SELECT coalesce(sum(allocation.quantity), 0) INTO used
        FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment existing
          ON existing.organization_id = allocation.organization_id
         AND existing.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.resource_id = NEW.resource_id AND allocation.is_active
          AND allocation.basis = 'scheduling' AND allocation.id <> NEW.id
          AND existing.source_location_id = assignment.source_location_id
          AND existing.status = 'reserved';
        IF available - used - NEW.quantity < 0 THEN
            RAISE EXCEPTION 'consumable available to promise exceeded' USING ERRCODE = '23514';
        END IF;
    ELSIF resource.nature = 'reusable_pool' THEN
        SELECT coalesce(quantity, 0) INTO available FROM public.resources_stockbalance
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND location_id = assignment.source_location_id FOR UPDATE;
        SELECT coalesce(sum(allocation.quantity), 0) INTO custody
        FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment existing
          ON existing.organization_id = allocation.organization_id
         AND existing.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.resource_id = NEW.resource_id AND allocation.is_active
          AND allocation.basis = 'custody' AND allocation.id <> NEW.id
          AND existing.source_location_id = assignment.source_location_id;
        IF NEW.basis = 'custody' THEN custody := custody + NEW.quantity; END IF;
        SELECT coalesce(sum(allocation.quantity), 0) INTO used
        FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment existing
          ON existing.organization_id = allocation.organization_id
         AND existing.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.resource_id = NEW.resource_id AND allocation.is_active
          AND allocation.id <> NEW.id
          AND existing.source_location_id = assignment.source_location_id
          AND allocation.resource_interval && NEW.resource_interval;
        SELECT coalesce(sum(value.quantity), 0) INTO unavailable
        FROM public.resources_resourceunavailability value
        WHERE value.organization_id = NEW.organization_id
          AND value.resource_id = NEW.resource_id AND value.is_active
          AND value.location_id = assignment.source_location_id
          AND value.unavailable_interval && NEW.resource_interval;
        IF available + custody - used - unavailable - NEW.quantity < 0 THEN
            RAISE EXCEPTION 'reusable pool capacity exceeded' USING ERRCODE = '23514';
        END IF;
    ELSIF resource.nature = 'serialized_asset' THEN
        SELECT * INTO asset FROM public.resources_serializedasset
        WHERE organization_id = NEW.organization_id AND id = NEW.serialized_asset_id FOR UPDATE;
        IF asset.id IS NULL OR NEW.quantity <> 1
           OR asset.resource_id <> NEW.resource_id
           OR asset.location_id <> assignment.source_location_id
           OR (NEW.basis = 'scheduling' AND asset.status <> 'available')
           OR (NEW.basis = 'custody' AND asset.status NOT IN ('available', 'custody'))
           OR EXISTS (
              SELECT 1 FROM public.resources_resourceunavailability value
              WHERE value.organization_id = NEW.organization_id
                AND value.serialized_asset_id = NEW.serialized_asset_id
                AND value.is_active AND value.unavailable_interval && NEW.resource_interval
           )
        THEN
            RAISE EXCEPTION 'serialized asset is unavailable' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.basis <> 'scheduling' THEN
            RAISE EXCEPTION 'supplied services cannot enter custody' USING ERRCODE = '23514';
        END IF;
        IF resource.declared_capacity IS NULL THEN
            RAISE EXCEPTION 'resource has no declared temporal capacity' USING ERRCODE = '23514';
        END IF;
        SELECT coalesce(sum(quantity), 0) INTO used
        FROM public.resources_resourcecapacityallocation
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND is_active AND id <> NEW.id AND resource_interval && NEW.resource_interval;
        SELECT coalesce(sum(quantity), 0) INTO unavailable
        FROM public.resources_resourceunavailability
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND is_active AND unavailable_interval && NEW.resource_interval;
        IF used + unavailable + NEW.quantity > resource.declared_capacity THEN
            RAISE EXCEPTION 'temporal resource capacity exceeded' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_resources_release_scheduling_capacity()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF OLD.status IN ('provisional', 'confirmed')
       AND NEW.status IN ('cancelled', 'expired', 'rescheduled') THEN
        UPDATE public.resources_resourcecapacityallocation allocation
        SET is_active = false
        FROM public.resources_resourceassignment assignment
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.reservation_id = NEW.id AND allocation.is_active
          AND allocation.basis = 'scheduling'
          AND assignment.organization_id = allocation.organization_id
          AND assignment.id = allocation.assignment_id;
        UPDATE public.resources_resourceassignment
        SET status = 'released'
        WHERE organization_id = NEW.organization_id AND reservation_id = NEW.id
          AND status = 'reserved';
        UPDATE public.resources_resourcerequirement
        SET status = 'cancelled'
        WHERE organization_id = NEW.organization_id AND reservation_id = NEW.id
          AND status IN ('open', 'satisfied');
        INSERT INTO public.resources_resourceevent (
            id, organization_id, aggregate_kind, aggregate_id, kind, payload,
            occurred_at, recorded_by_membership_id, created_at
        ) VALUES (
            pg_catalog.gen_random_uuid(), NEW.organization_id, 'reservation', NEW.id,
            'schedule_capacity_released',
            pg_catalog.jsonb_build_object('previous_status', OLD.status, 'status', NEW.status),
            pg_catalog.statement_timestamp(), NULL, pg_catalog.statement_timestamp()
        );
    END IF;
    RETURN NEW;
END;
$function$;
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS resources_requirement_temporal_source_guard
ON public.resources_resourcerequirement;
DROP FUNCTION IF EXISTS public.claridez_resources_guard_requirement_temporal_source();
ALTER TABLE public.resources_resourcerequirement
DROP CONSTRAINT IF EXISTS res_requirement_operation_window_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0006_p13_integrity"),
        ("resources", "0003_resourcerequirement_operational_window_and_more"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
