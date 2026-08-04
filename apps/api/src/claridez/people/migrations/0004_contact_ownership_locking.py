# ruff: noqa: E501

from django.db import migrations

FORWARD = r"""
CREATE OR REPLACE FUNCTION public.claridez_people_lock_contact_organizations(
    tenant_ids uuid[]
)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    tenant_id uuid;
BEGIN
    FOR tenant_id IN
        SELECT candidate
        FROM unnest(tenant_ids) AS candidate
        WHERE candidate IS NOT NULL
        GROUP BY candidate
        ORDER BY candidate
    LOOP
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                'claridez:people:contact-ownership:' || tenant_id::text,
                0
            )
        );
    END LOOP;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_lock_contact_organizations(uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_people_lock_contact_organizations(uuid[])
TO claridez_app, claridez_migrator, claridez_test_runner;
GRANT EXECUTE ON FUNCTION public.claridez_people_canonical_id(uuid, uuid)
TO claridez_app, claridez_migrator, claridez_test_runner;

CREATE OR REPLACE FUNCTION public.claridez_people_guard_person_contacts()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    canonical_owner_id uuid;
    conflicting_owner_id uuid;
    alias_owner_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        PERFORM public.claridez_people_lock_contact_organizations(
            ARRAY[OLD.organization_id, NEW.organization_id]
        );
    ELSE
        PERFORM public.claridez_people_lock_contact_organizations(
            ARRAY[NEW.organization_id]
        );
    END IF;

    canonical_owner_id := public.claridez_people_canonical_id(NEW.organization_id, NEW.id);

    SELECT candidate.owner_id
    INTO conflicting_owner_id
    FROM (
        SELECT public.claridez_people_canonical_id(person.organization_id, person.id) AS owner_id
        FROM public.commercial_person AS person
        WHERE person.organization_id = NEW.organization_id
          AND (
              person.phone_e164 = NEW.phone_e164
              OR (NEW.email <> '' AND person.email = NEW.email)
          )
        UNION ALL
        SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id) AS owner_id
        FROM public.people_personcontactalias AS alias
        WHERE alias.organization_id = NEW.organization_id
          AND (
              (alias.kind = 'phone' AND alias.normalized_value = NEW.phone_e164)
              OR (NEW.email <> '' AND alias.kind = 'email' AND alias.normalized_value = NEW.email)
          )
    ) AS candidate
    WHERE candidate.owner_id IS DISTINCT FROM canonical_owner_id
    LIMIT 1;
    IF conflicting_owner_id IS NOT NULL THEN
        RAISE EXCEPTION 'contact belongs to another canonical person' USING ERRCODE = '23505';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.phone_e164 IS DISTINCT FROM NEW.phone_e164 THEN
        SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id)
        INTO alias_owner_id
        FROM public.people_personcontactalias AS alias
        WHERE alias.organization_id = OLD.organization_id
          AND alias.kind = 'phone'
          AND alias.normalized_value = OLD.phone_e164
        LIMIT 1;
        IF alias_owner_id IS NOT NULL AND alias_owner_id <> canonical_owner_id THEN
            RAISE EXCEPTION 'historical phone belongs to another person' USING ERRCODE = '23505';
        END IF;
        IF alias_owner_id IS NULL THEN
            INSERT INTO public.people_personcontactalias (
                id, organization_id, person_id, source_person_id, source_revision,
                kind, normalized_value, created_at
            ) VALUES (
                gen_random_uuid(), OLD.organization_id, OLD.id, OLD.id, OLD.revision,
                'phone', OLD.phone_e164, CURRENT_TIMESTAMP
            );
        END IF;
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.email <> ''
       AND OLD.email IS DISTINCT FROM NEW.email THEN
        SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id)
        INTO alias_owner_id
        FROM public.people_personcontactalias AS alias
        WHERE alias.organization_id = OLD.organization_id
          AND alias.kind = 'email'
          AND alias.normalized_value = OLD.email
        LIMIT 1;
        IF alias_owner_id IS NOT NULL AND alias_owner_id <> canonical_owner_id THEN
            RAISE EXCEPTION 'historical email belongs to another person' USING ERRCODE = '23505';
        END IF;
        IF alias_owner_id IS NULL THEN
            INSERT INTO public.people_personcontactalias (
                id, organization_id, person_id, source_person_id, source_revision,
                kind, normalized_value, created_at
            ) VALUES (
                gen_random_uuid(), OLD.organization_id, OLD.id, OLD.id, OLD.revision,
                'email', OLD.email, CURRENT_TIMESTAMP
            );
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_guard_person_contacts() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_people_guard_contact_alias()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    canonical_owner_id uuid;
    source_owner_id uuid;
    conflicting_owner_id uuid;
BEGIN
    PERFORM public.claridez_people_lock_contact_organizations(
        ARRAY[NEW.organization_id]
    );

    canonical_owner_id := public.claridez_people_canonical_id(
        NEW.organization_id, NEW.person_id
    );
    source_owner_id := public.claridez_people_canonical_id(
        NEW.organization_id, NEW.source_person_id
    );
    IF canonical_owner_id IS NULL
       OR source_owner_id IS NULL
       OR canonical_owner_id <> source_owner_id THEN
        RAISE EXCEPTION 'contact alias must remain inside one canonical cluster' USING ERRCODE = '23514';
    END IF;

    SELECT candidate.owner_id
    INTO conflicting_owner_id
    FROM (
        SELECT public.claridez_people_canonical_id(person.organization_id, person.id) AS owner_id
        FROM public.commercial_person AS person
        WHERE person.organization_id = NEW.organization_id
          AND (
              (NEW.kind = 'phone' AND person.phone_e164 = NEW.normalized_value)
              OR (NEW.kind = 'email' AND person.email = NEW.normalized_value)
          )
        UNION ALL
        SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id) AS owner_id
        FROM public.people_personcontactalias AS alias
        WHERE alias.organization_id = NEW.organization_id
          AND alias.kind = NEW.kind
          AND alias.normalized_value = NEW.normalized_value
    ) AS candidate
    WHERE candidate.owner_id IS DISTINCT FROM canonical_owner_id
    LIMIT 1;
    IF conflicting_owner_id IS NOT NULL THEN
        RAISE EXCEPTION 'contact alias belongs to another canonical person' USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_guard_contact_alias() FROM PUBLIC;
"""

REVERSE = r"""
CREATE OR REPLACE FUNCTION public.claridez_people_guard_person_contacts()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    owner_id uuid;
    alias_owner_id uuid;
BEGIN
    owner_id := public.claridez_people_canonical_id(NEW.organization_id, NEW.id);

    SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id)
    INTO alias_owner_id
    FROM public.people_personcontactalias AS alias
    WHERE alias.organization_id = NEW.organization_id
      AND (
          (alias.kind = 'phone' AND alias.normalized_value = NEW.phone_e164)
          OR (NEW.email <> '' AND alias.kind = 'email' AND alias.normalized_value = NEW.email)
      )
    LIMIT 1;
    IF alias_owner_id IS NOT NULL AND alias_owner_id <> owner_id THEN
        RAISE EXCEPTION 'contact belongs to another person history' USING ERRCODE = '23505';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.phone_e164 IS DISTINCT FROM NEW.phone_e164 THEN
        SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id)
        INTO alias_owner_id
        FROM public.people_personcontactalias AS alias
        WHERE alias.organization_id = OLD.organization_id
          AND alias.kind = 'phone'
          AND alias.normalized_value = OLD.phone_e164
        LIMIT 1;
        IF alias_owner_id IS NOT NULL AND alias_owner_id <> owner_id THEN
            RAISE EXCEPTION 'historical phone belongs to another person' USING ERRCODE = '23505';
        END IF;
        IF alias_owner_id IS NULL THEN
            INSERT INTO public.people_personcontactalias (
                id, organization_id, person_id, source_person_id, source_revision,
                kind, normalized_value, created_at
            ) VALUES (
                gen_random_uuid(), OLD.organization_id, OLD.id, OLD.id, OLD.revision,
                'phone', OLD.phone_e164, CURRENT_TIMESTAMP
            );
        END IF;
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.email <> ''
       AND OLD.email IS DISTINCT FROM NEW.email THEN
        SELECT public.claridez_people_canonical_id(alias.organization_id, alias.person_id)
        INTO alias_owner_id
        FROM public.people_personcontactalias AS alias
        WHERE alias.organization_id = OLD.organization_id
          AND alias.kind = 'email'
          AND alias.normalized_value = OLD.email
        LIMIT 1;
        IF alias_owner_id IS NOT NULL AND alias_owner_id <> owner_id THEN
            RAISE EXCEPTION 'historical email belongs to another person' USING ERRCODE = '23505';
        END IF;
        IF alias_owner_id IS NULL THEN
            INSERT INTO public.people_personcontactalias (
                id, organization_id, person_id, source_person_id, source_revision,
                kind, normalized_value, created_at
            ) VALUES (
                gen_random_uuid(), OLD.organization_id, OLD.id, OLD.id, OLD.revision,
                'email', OLD.email, CURRENT_TIMESTAMP
            );
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_people_guard_contact_alias()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    owner_id uuid;
    source_owner_id uuid;
    current_owner_id uuid;
BEGIN
    owner_id := public.claridez_people_canonical_id(NEW.organization_id, NEW.person_id);
    source_owner_id := public.claridez_people_canonical_id(
        NEW.organization_id, NEW.source_person_id
    );
    IF owner_id IS NULL OR source_owner_id IS NULL OR owner_id <> source_owner_id THEN
        RAISE EXCEPTION 'contact alias must remain inside one canonical cluster' USING ERRCODE = '23514';
    END IF;

    SELECT public.claridez_people_canonical_id(person.organization_id, person.id)
    INTO current_owner_id
    FROM public.commercial_person AS person
    WHERE person.organization_id = NEW.organization_id
      AND (
          (NEW.kind = 'phone' AND person.phone_e164 = NEW.normalized_value)
          OR (NEW.kind = 'email' AND person.email = NEW.normalized_value)
      )
      AND public.claridez_people_canonical_id(person.organization_id, person.id) <> owner_id
    LIMIT 1;
    IF current_owner_id IS NOT NULL THEN
        RAISE EXCEPTION 'contact alias belongs to another current person' USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$function$;

DROP FUNCTION IF EXISTS public.claridez_people_lock_contact_organizations(uuid[]);
REVOKE EXECUTE ON FUNCTION public.claridez_people_canonical_id(uuid, uuid)
FROM claridez_app, claridez_migrator, claridez_test_runner;
"""


class Migration(migrations.Migration):
    dependencies = [("people", "0003_contact_history_and_consent_integrity")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
