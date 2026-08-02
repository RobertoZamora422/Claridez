from django.db import migrations

CATALOG_HISTORY_FORWARD = r"""
CREATE FUNCTION public.claridez_guard_catalog_head_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    payload_changed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.revision <> 1 THEN
            RAISE EXCEPTION 'catalog head must start at revision one' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'catalog_eventtype' THEN
        IF ROW(NEW.id, NEW.organization_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id, OLD.organization_id, OLD.created_at) THEN
            RAISE EXCEPTION 'catalog event type identity is immutable' USING ERRCODE = '23514';
        END IF;
        payload_changed := ROW(NEW.name, NEW.is_active)
            IS DISTINCT FROM ROW(OLD.name, OLD.is_active);
    ELSIF TG_TABLE_NAME = 'catalog_catalogitem' THEN
        IF ROW(NEW.id, NEW.organization_id, NEW.kind, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id, OLD.organization_id, OLD.kind, OLD.created_at) THEN
            RAISE EXCEPTION 'catalog item identity is immutable' USING ERRCODE = '23514';
        END IF;
        payload_changed := ROW(NEW.name, NEW.description, NEW.unit_label, NEW.is_active)
            IS DISTINCT FROM ROW(OLD.name, OLD.description, OLD.unit_label, OLD.is_active);
    ELSE
        RAISE EXCEPTION 'unsupported catalog head table' USING ERRCODE = '23514';
    END IF;

    IF payload_changed AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'catalog mutation requires the next revision' USING ERRCODE = '23514';
    ELSIF NOT payload_changed AND NEW.revision <> OLD.revision THEN
        RAISE EXCEPTION 'catalog revision cannot change without payload' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_catalog_head_mutation() FROM PUBLIC;

CREATE TRIGGER catalog_eventtype_head_mutation_guard
BEFORE INSERT OR UPDATE ON public.catalog_eventtype
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_catalog_head_mutation();
CREATE TRIGGER catalog_item_head_mutation_guard
BEFORE INSERT OR UPDATE ON public.catalog_catalogitem
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_catalog_head_mutation();

CREATE FUNCTION public.claridez_validate_event_type_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_organization uuid;
    target_event_type uuid;
    previous_context text;
    head_revision integer;
    head_name text;
    head_active boolean;
    revision_count bigint;
    minimum_revision integer;
    maximum_revision integer;
    matching_head_count bigint;
BEGIN
    target_organization := NEW.organization_id;
    IF TG_TABLE_NAME = 'catalog_eventtype' THEN
        target_event_type := NEW.id;
    ELSE
        target_event_type := NEW.event_type_id;
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', target_organization::text, true
    );
    BEGIN
        SELECT revision, name, is_active
        INTO head_revision, head_name, head_active
        FROM public.catalog_eventtype
        WHERE organization_id = target_organization AND id = target_event_type;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'catalog event type head is missing' USING ERRCODE = '23514';
        END IF;

        SELECT
            count(*), min(revision), max(revision),
            count(*) FILTER (
                WHERE revision = head_revision
                  AND name = head_name
                  AND is_active = head_active
            )
        INTO revision_count, minimum_revision, maximum_revision, matching_head_count
        FROM public.catalog_eventtyperevision
        WHERE organization_id = target_organization AND event_type_id = target_event_type;

        IF revision_count <> head_revision
           OR minimum_revision <> 1
           OR maximum_revision <> head_revision
           OR matching_head_count <> 1 THEN
            RAISE EXCEPTION 'catalog event type history is inconsistent'
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
REVOKE ALL ON FUNCTION public.claridez_validate_event_type_history() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER catalog_eventtype_history_guard
AFTER INSERT OR UPDATE ON public.catalog_eventtype
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_event_type_history();
CREATE CONSTRAINT TRIGGER catalog_eventtyperevision_history_guard
AFTER INSERT ON public.catalog_eventtyperevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_event_type_history();

CREATE FUNCTION public.claridez_validate_catalog_item_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_organization uuid;
    target_item uuid;
    previous_context text;
    head_revision integer;
    head_kind text;
    head_name text;
    head_description text;
    head_unit_label text;
    head_active boolean;
    revision_count bigint;
    minimum_revision integer;
    maximum_revision integer;
    matching_head_count bigint;
BEGIN
    target_organization := NEW.organization_id;
    IF TG_TABLE_NAME = 'catalog_catalogitem' THEN
        target_item := NEW.id;
    ELSIF TG_TABLE_NAME = 'catalog_catalogitemrevision' THEN
        target_item := NEW.item_id;
    ELSE
        target_item := NEW.package_id;
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', target_organization::text, true
    );
    BEGIN
        SELECT revision, kind, name, description, unit_label, is_active
        INTO head_revision, head_kind, head_name, head_description, head_unit_label, head_active
        FROM public.catalog_catalogitem
        WHERE organization_id = target_organization AND id = target_item;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'catalog item head is missing' USING ERRCODE = '23514';
        END IF;

        SELECT
            count(*), min(revision), max(revision),
            count(*) FILTER (
                WHERE revision = head_revision
                  AND kind = head_kind
                  AND name = head_name
                  AND description = head_description
                  AND unit_label = head_unit_label
                  AND is_active = head_active
            )
        INTO revision_count, minimum_revision, maximum_revision, matching_head_count
        FROM public.catalog_catalogitemrevision
        WHERE organization_id = target_organization AND item_id = target_item;

        IF revision_count <> head_revision
           OR minimum_revision <> 1
           OR maximum_revision <> head_revision
           OR matching_head_count <> 1 THEN
            RAISE EXCEPTION 'catalog item history is inconsistent' USING ERRCODE = '23514';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.catalog_catalogitemrevision AS item_revision
            LEFT JOIN LATERAL (
                SELECT
                    count(*) AS component_count,
                    min(component.position) AS minimum_position,
                    max(component.position) AS maximum_position,
                    coalesce(
                        jsonb_agg(
                            jsonb_build_object(
                                'item_id', component.component_id::text,
                                'revision_id', component.component_revision_id::text,
                                'revision', component_revision.revision,
                                'kind', component_revision.kind,
                                'name', component_revision.name,
                                'unit_label', component_revision.unit_label,
                                'quantity', component.quantity::text
                            ) ORDER BY component.position
                        ),
                        '[]'::jsonb
                    ) AS snapshot
                FROM public.catalog_packagecomponent AS component
                JOIN public.catalog_catalogitemrevision AS component_revision
                  ON component_revision.organization_id = component.organization_id
                 AND component_revision.id = component.component_revision_id
                WHERE component.organization_id = item_revision.organization_id
                  AND component.package_id = item_revision.item_id
                  AND component.package_revision = item_revision.revision
            ) AS projection ON true
            WHERE item_revision.organization_id = target_organization
              AND item_revision.item_id = target_item
              AND (
                  item_revision.kind IS DISTINCT FROM head_kind
                  OR (
                      item_revision.kind = 'package'
                      AND (
                          projection.component_count = 0
                          OR projection.minimum_position <> 1
                          OR projection.maximum_position <> projection.component_count
                          OR item_revision.package_components IS DISTINCT FROM projection.snapshot
                      )
                  )
                  OR (
                      item_revision.kind <> 'package'
                      AND (
                          item_revision.package_components IS DISTINCT FROM '[]'::jsonb
                          OR projection.component_count <> 0
                      )
                  )
              )
        ) THEN
            RAISE EXCEPTION 'catalog package composition is inconsistent'
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
REVOKE ALL ON FUNCTION public.claridez_validate_catalog_item_history() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER catalog_item_history_guard
AFTER INSERT OR UPDATE ON public.catalog_catalogitem
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_catalog_item_history();
CREATE CONSTRAINT TRIGGER catalog_itemrevision_history_guard
AFTER INSERT ON public.catalog_catalogitemrevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_catalog_item_history();
CREATE CONSTRAINT TRIGGER catalog_packagecomponent_history_guard
AFTER INSERT ON public.catalog_packagecomponent
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_catalog_item_history();

DO $block$
DECLARE
    target_organization uuid;
BEGIN
    FOR target_organization IN
        SELECT id FROM public.organizations_organization ORDER BY id
    LOOP
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', target_organization::text, true
        );
        UPDATE public.catalog_eventtype
        SET updated_at = updated_at
        WHERE organization_id = target_organization;
        UPDATE public.catalog_catalogitem
        SET updated_at = updated_at
        WHERE organization_id = target_organization;
    END LOOP;
    PERFORM pg_catalog.set_config('claridez.organization_id', '', true);
END
$block$;
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;
"""


CATALOG_HISTORY_REVERSE = r"""
DROP TRIGGER IF EXISTS catalog_packagecomponent_history_guard
    ON public.catalog_packagecomponent;
DROP TRIGGER IF EXISTS catalog_itemrevision_history_guard
    ON public.catalog_catalogitemrevision;
DROP TRIGGER IF EXISTS catalog_item_history_guard ON public.catalog_catalogitem;
DROP FUNCTION IF EXISTS public.claridez_validate_catalog_item_history();
DROP TRIGGER IF EXISTS catalog_eventtyperevision_history_guard
    ON public.catalog_eventtyperevision;
DROP TRIGGER IF EXISTS catalog_eventtype_history_guard ON public.catalog_eventtype;
DROP FUNCTION IF EXISTS public.claridez_validate_event_type_history();
DROP TRIGGER IF EXISTS catalog_item_head_mutation_guard ON public.catalog_catalogitem;
DROP TRIGGER IF EXISTS catalog_eventtype_head_mutation_guard ON public.catalog_eventtype;
DROP FUNCTION IF EXISTS public.claridez_guard_catalog_head_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [migrations.RunSQL(CATALOG_HISTORY_FORWARD, CATALOG_HISTORY_REVERSE)]
