# ruff: noqa: E501

from django.db import migrations

FORWARD = r"""
CREATE OR REPLACE FUNCTION public.claridez_crm_guard_link_context()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    request_person uuid;
    request_canonical uuid;
BEGIN
    IF NEW.event_request_id IS NOT NULL THEN
        SELECT person_id INTO request_person
        FROM public.commercial_eventrequest
        WHERE organization_id = NEW.organization_id AND id = NEW.event_request_id;

        WITH RECURSIVE path(person_id) AS (
            SELECT request_person
            UNION ALL
            SELECT merge.target_person_id
            FROM public.people_personmerge AS merge
            JOIN path ON merge.source_person_id = path.person_id
            WHERE merge.organization_id = NEW.organization_id
        )
        SELECT person_id INTO request_canonical
        FROM path
        WHERE NOT EXISTS (
            SELECT 1 FROM public.people_personmerge AS outgoing
            WHERE outgoing.organization_id = NEW.organization_id
              AND outgoing.source_person_id = path.person_id
        )
        LIMIT 1;

        IF request_canonical IS NULL OR request_canonical <> NEW.person_id THEN
            RAISE EXCEPTION 'crm relation does not match request person' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_crm_guard_link_context() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_crm_guard_interaction_correction()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    original record;
BEGIN
    IF NEW.correction_of_id IS NOT NULL THEN
        SELECT organization_id, person_id, event_request_id INTO original
        FROM public.crm_interaction
        WHERE organization_id = NEW.organization_id AND id = NEW.correction_of_id;
        IF NOT FOUND
           OR original.person_id <> NEW.person_id
           OR original.event_request_id IS DISTINCT FROM NEW.event_request_id THEN
            RAISE EXCEPTION 'interaction correction context mismatch' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_crm_guard_interaction_correction() FROM PUBLIC;

DROP TRIGGER IF EXISTS crm_interaction_correction_guard ON public.crm_interaction;
CREATE TRIGGER crm_interaction_correction_guard
BEFORE INSERT ON public.crm_interaction
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_guard_interaction_correction();
"""


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, migrations.RunSQL.noop)]
