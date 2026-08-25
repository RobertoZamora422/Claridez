from django.db import migrations, models
from django.db.models import Q

HARDENING_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_resources_guard_allocation()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE assignment record; reservation record; resource record; asset record;
        available numeric(20,6); custody numeric(20,6); used numeric(20,6);
        unavailable numeric(20,6);
BEGIN
    IF NOT NEW.is_active THEN RETURN NEW; END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'resources:' || NEW.organization_id::text || ':resource:' || NEW.resource_id::text, 0
    ));
    SELECT * INTO assignment FROM public.resources_resourceassignment
    WHERE organization_id = NEW.organization_id AND id = NEW.assignment_id FOR UPDATE;
    SELECT id, root_id, status, hold_expires_at, event_interval INTO reservation
    FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id FOR UPDATE;
    SELECT * INTO resource FROM public.resources_resource
    WHERE organization_id = NEW.organization_id AND id = NEW.resource_id FOR UPDATE;
    IF assignment.id IS NULL OR resource.id IS NULL
       OR assignment.reservation_id <> NEW.reservation_id
       OR assignment.root_reservation_id <> reservation.root_id
       OR assignment.resource_id <> NEW.resource_id
       OR assignment.quantity <> NEW.quantity
    THEN
        RAISE EXCEPTION 'resource allocation does not match its assignment' USING ERRCODE = '23514';
    END IF;
    IF NEW.basis = 'scheduling' AND (
       reservation.id IS NULL OR reservation.status NOT IN ('provisional', 'confirmed')
       OR (reservation.status = 'provisional'
           AND reservation.hold_expires_at <= transaction_timestamp())
       OR assignment.status <> 'reserved'
       OR assignment.resource_interval <> NEW.resource_interval
       OR NEW.resource_interval <> reservation.event_interval
    ) THEN
        RAISE EXCEPTION 'resource allocation does not match current scheduling interval'
        USING ERRCODE = '23514';
    ELSIF NEW.basis = 'custody' AND (
       assignment.status <> 'custody' OR NOT upper_inf(NEW.resource_interval)
    ) THEN
        RAISE EXCEPTION 'custody capacity projection is inconsistent' USING ERRCODE = '23514';
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

CREATE OR REPLACE FUNCTION public.claridez_resources_check_assignment_projection(
    target_organization uuid, target_assignment uuid
) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE assignment record; allocation record; asset_status text;
BEGIN
    SELECT * INTO assignment FROM public.resources_resourceassignment
    WHERE organization_id = target_organization AND id = target_assignment;
    IF assignment.id IS NULL THEN RETURN; END IF;
    SELECT * INTO allocation FROM public.resources_resourcecapacityallocation
    WHERE organization_id = target_organization AND assignment_id = target_assignment;
    IF allocation.id IS NULL
       OR (assignment.status = 'reserved' AND (
            NOT allocation.is_active OR allocation.basis <> 'scheduling'
       ))
       OR (assignment.status = 'custody' AND (
            NOT allocation.is_active OR allocation.basis <> 'custody'
            OR NOT upper_inf(allocation.resource_interval)
       ))
       OR (assignment.status IN ('issued', 'fulfilled', 'returned', 'released', 'cancelled')
           AND allocation.is_active)
    THEN
        RAISE EXCEPTION 'assignment and capacity projection diverge' USING ERRCODE = '23514';
    END IF;
    IF assignment.serialized_asset_id IS NOT NULL THEN
        SELECT status INTO asset_status FROM public.resources_serializedasset
        WHERE organization_id = target_organization AND id = assignment.serialized_asset_id;
        IF (assignment.status = 'reserved' AND asset_status <> 'available')
           OR (assignment.status = 'custody' AND asset_status <> 'custody')
           OR (assignment.status = 'returned' AND asset_status <> 'available')
        THEN
            RAISE EXCEPTION 'serialized asset physical state diverges from assignment'
            USING ERRCODE = '23514';
        END IF;
    END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_resources_guard_unavailability()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE resource record; asset record; capacity numeric(20,6); used numeric(20,6);
        custody numeric(20,6); existing_unavailable numeric(20,6);
        balance numeric(20,6); corrected record;
BEGIN
    IF NOT NEW.is_active THEN RETURN NEW; END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'resources:' || NEW.organization_id::text || ':resource:' || NEW.resource_id::text, 0
    ));
    SELECT * INTO resource FROM public.resources_resource
    WHERE organization_id = NEW.organization_id AND id = NEW.resource_id FOR UPDATE;
    capacity := resource.declared_capacity;
    IF resource.id IS NULL
       OR (resource.nature = 'supplied_service' AND (
            NEW.location_id IS NOT NULL OR NEW.serialized_asset_id IS NOT NULL
       ))
       OR (resource.nature <> 'supplied_service' AND NEW.location_id IS NULL)
       OR (resource.nature = 'serialized_asset' AND (
            NEW.serialized_asset_id IS NULL OR NEW.quantity <> 1
       ))
    THEN
        RAISE EXCEPTION 'resource unavailability shape is inconsistent' USING ERRCODE = '23514';
    END IF;
    IF NEW.serialized_asset_id IS NOT NULL THEN
        SELECT * INTO asset FROM public.resources_serializedasset
        WHERE organization_id = NEW.organization_id AND id = NEW.serialized_asset_id FOR UPDATE;
        IF asset.id IS NULL OR asset.resource_id <> NEW.resource_id
           OR asset.location_id <> NEW.location_id OR asset.status = 'retired'
        THEN
            RAISE EXCEPTION 'resource unavailability asset is inconsistent' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.resources_resourcecapacityallocation
            WHERE organization_id = NEW.organization_id
              AND serialized_asset_id = NEW.serialized_asset_id AND is_active
              AND resource_interval && NEW.unavailable_interval
        ) THEN
            RAISE EXCEPTION 'serialized asset is allocated in interval' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.corrects_id IS NOT NULL THEN
        SELECT * INTO corrected FROM public.resources_resourceunavailability
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id FOR UPDATE;
        IF corrected.id IS NULL OR corrected.is_active
           OR corrected.resource_id <> NEW.resource_id
           OR corrected.serialized_asset_id IS DISTINCT FROM NEW.serialized_asset_id
           OR corrected.location_id IS DISTINCT FROM NEW.location_id
        THEN
            RAISE EXCEPTION 'resource unavailability correction is inconsistent'
            USING ERRCODE = '23514';
        END IF;
    END IF;
    IF resource.nature = 'consumable' THEN
        SELECT coalesce(quantity, 0) INTO balance FROM public.resources_stockbalance
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND location_id = NEW.location_id FOR UPDATE;
        SELECT coalesce(sum(quantity), 0) INTO existing_unavailable
        FROM public.resources_resourceunavailability
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND location_id = NEW.location_id AND is_active AND id <> NEW.id
          AND unavailable_interval && NEW.unavailable_interval;
        IF existing_unavailable + NEW.quantity > balance THEN
            RAISE EXCEPTION 'physical unavailability exceeds on-hand stock' USING ERRCODE = '23514';
        END IF;
    ELSIF resource.nature = 'reusable_pool' THEN
        SELECT coalesce(quantity, 0) INTO balance FROM public.resources_stockbalance
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND location_id = NEW.location_id FOR UPDATE;
        SELECT coalesce(sum(allocation.quantity), 0) INTO custody
        FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment assignment
          ON assignment.organization_id = allocation.organization_id
         AND assignment.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.resource_id = NEW.resource_id AND allocation.is_active
          AND allocation.basis = 'custody'
          AND assignment.source_location_id = NEW.location_id;
        SELECT coalesce(sum(allocation.quantity), 0) INTO used
        FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment assignment
          ON assignment.organization_id = allocation.organization_id
         AND assignment.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.resource_id = NEW.resource_id AND allocation.is_active
          AND assignment.source_location_id = NEW.location_id
          AND allocation.resource_interval && NEW.unavailable_interval;
        SELECT coalesce(sum(quantity), 0) INTO existing_unavailable
        FROM public.resources_resourceunavailability
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND location_id = NEW.location_id AND is_active AND id <> NEW.id
          AND unavailable_interval && NEW.unavailable_interval;
        IF used + existing_unavailable + NEW.quantity > balance + custody THEN
            RAISE EXCEPTION 'reusable pool unavailability exceeds interval capacity'
            USING ERRCODE = '23514';
        END IF;
    ELSIF resource.nature = 'supplied_service' AND capacity IS NOT NULL THEN
        SELECT coalesce(sum(quantity), 0) INTO used
        FROM public.resources_resourcecapacityallocation
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND is_active AND resource_interval && NEW.unavailable_interval;
        SELECT coalesce(sum(quantity), 0) INTO existing_unavailable
        FROM public.resources_resourceunavailability
        WHERE organization_id = NEW.organization_id AND resource_id = NEW.resource_id
          AND is_active AND id <> NEW.id AND unavailable_interval && NEW.unavailable_interval;
        IF used + existing_unavailable + NEW.quantity > capacity THEN
            RAISE EXCEPTION 'unavailability exceeds declared capacity' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_resources_guard_asset_physical_state()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF NEW.status NOT IN ('available', 'custody', 'retired') THEN
        RAISE EXCEPTION 'serialized asset status is not physical' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment assignment
          ON assignment.organization_id = allocation.organization_id
         AND assignment.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.serialized_asset_id = NEW.id AND allocation.is_active
          AND (allocation.resource_id <> NEW.resource_id
               OR assignment.source_location_id <> NEW.location_id)
    ) THEN
        RAISE EXCEPTION 'serialized asset identity diverges from active allocation'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'custody' AND NOT EXISTS (
        SELECT 1 FROM public.resources_resourcecapacityallocation allocation
        JOIN public.resources_resourceassignment assignment
          ON assignment.organization_id = allocation.organization_id
         AND assignment.id = allocation.assignment_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.serialized_asset_id = NEW.id AND allocation.is_active
          AND allocation.basis = 'custody' AND assignment.status = 'custody'
    ) THEN
        RAISE EXCEPTION 'serialized asset custody lacks active custody fact'
        USING ERRCODE = '23514';
    ELSIF NEW.status = 'available' AND EXISTS (
        SELECT 1 FROM public.resources_resourcecapacityallocation allocation
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.serialized_asset_id = NEW.id AND allocation.is_active
          AND allocation.basis = 'custody'
    ) THEN
        RAISE EXCEPTION 'serialized asset in custody cannot be available'
        USING ERRCODE = '23514';
    ELSIF NEW.status = 'retired' AND (
        EXISTS (
            SELECT 1 FROM public.resources_resourcecapacityallocation allocation
            WHERE allocation.organization_id = NEW.organization_id
              AND allocation.serialized_asset_id = NEW.id AND allocation.is_active
        ) OR EXISTS (
            SELECT 1 FROM public.resources_resourceunavailability value
            WHERE value.organization_id = NEW.organization_id
              AND value.serialized_asset_id = NEW.id AND value.is_active
        )
    ) THEN
        RAISE EXCEPTION 'serialized asset with active temporal facts cannot be retired'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS resources_asset_physical_state_guard
ON public.resources_serializedasset;
CREATE TRIGGER resources_asset_physical_state_guard
BEFORE INSERT OR UPDATE OF status, resource_id, location_id
ON public.resources_serializedasset
FOR EACH ROW EXECUTE FUNCTION public.claridez_resources_guard_asset_physical_state();
"""


HARDENING_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS resources_asset_physical_state_guard
ON public.resources_serializedasset;
DROP FUNCTION IF EXISTS public.claridez_resources_guard_asset_physical_state();
"""


class Migration(migrations.Migration):
    dependencies = [("resources", "0001_initial")]

    operations = [
        migrations.RunSQL(
            "UPDATE public.resources_serializedasset SET status = 'available' "
            "WHERE status IN ('reserved', 'maintenance')",
            migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="serializedasset",
            name="status",
            field=models.CharField(
                choices=[
                    ("available", "Disponible"),
                    ("custody", "En custodia"),
                    ("retired", "Retirado"),
                ],
                default="available",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="serializedasset",
            constraint=models.CheckConstraint(
                condition=Q(status__in=["available", "custody", "retired"]),
                name="resources_asset_physical_status_ck",
            ),
        ),
        migrations.RunSQL(HARDENING_SQL, HARDENING_REVERSE_SQL),
    ]
