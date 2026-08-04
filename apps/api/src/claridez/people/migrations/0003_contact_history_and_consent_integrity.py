# ruff: noqa: E501

import django.db.models.functions.text
from django.db import migrations, models

FORWARD = r"""
CREATE OR REPLACE FUNCTION public.claridez_people_canonical_id(
    tenant_id uuid,
    requested_person_id uuid
)
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $function$
    WITH RECURSIVE path(person_id) AS (
        SELECT requested_person_id
        UNION ALL
        SELECT merge.target_person_id
        FROM public.people_personmerge AS merge
        JOIN path ON merge.source_person_id = path.person_id
        WHERE merge.organization_id = tenant_id
    )
    SELECT path.person_id
    FROM path
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.people_personmerge AS outgoing
        WHERE outgoing.organization_id = tenant_id
          AND outgoing.source_person_id = path.person_id
    )
    LIMIT 1;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_canonical_id(uuid, uuid) FROM PUBLIC;

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
REVOKE ALL ON FUNCTION public.claridez_people_guard_person_contacts() FROM PUBLIC;

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
REVOKE ALL ON FUNCTION public.claridez_people_guard_contact_alias() FROM PUBLIC;

DROP TRIGGER IF EXISTS commercial_person_contact_guard ON public.commercial_person;
CREATE TRIGGER commercial_person_contact_guard
BEFORE INSERT OR UPDATE OF organization_id, phone_e164, email ON public.commercial_person
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_guard_person_contacts();
DROP TRIGGER IF EXISTS people_personcontactalias_owner_guard ON public.people_personcontactalias;
CREATE TRIGGER people_personcontactalias_owner_guard
BEFORE INSERT ON public.people_personcontactalias
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_guard_contact_alias();

CREATE OR REPLACE FUNCTION public.claridez_people_guard_consent_correction()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    original record;
BEGIN
    IF NEW.event_type = 'correction' AND NEW.corrects_id IS NULL THEN
        RAISE EXCEPTION 'consent correction requires original evidence' USING ERRCODE = '23514';
    END IF;
    IF NEW.event_type <> 'correction' AND NEW.corrects_id IS NOT NULL THEN
        RAISE EXCEPTION 'only corrections may reference original evidence' USING ERRCODE = '23514';
    END IF;
    IF NEW.corrects_id IS NOT NULL THEN
        SELECT organization_id, person_id, purpose, channel INTO original
        FROM public.people_consentevent
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id;
        IF NOT FOUND
           OR public.claridez_people_canonical_id(original.organization_id, original.person_id)
              IS DISTINCT FROM
              public.claridez_people_canonical_id(NEW.organization_id, NEW.person_id)
           OR original.purpose <> NEW.purpose
           OR original.channel <> NEW.channel THEN
            RAISE EXCEPTION 'consent correction context mismatch' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_guard_consent_correction() FROM PUBLIC;
"""

REVERSE = r"""
CREATE OR REPLACE FUNCTION public.claridez_people_guard_consent_correction()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    original record;
BEGIN
    IF NEW.event_type = 'correction' AND NEW.corrects_id IS NULL THEN
        RAISE EXCEPTION 'consent correction requires original evidence' USING ERRCODE = '23514';
    END IF;
    IF NEW.event_type <> 'correction' AND NEW.corrects_id IS NOT NULL THEN
        RAISE EXCEPTION 'only corrections may reference original evidence' USING ERRCODE = '23514';
    END IF;
    IF NEW.corrects_id IS NOT NULL THEN
        SELECT organization_id, person_id, purpose, channel INTO original
        FROM public.people_consentevent
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id;
        IF NOT FOUND
           OR original.person_id <> NEW.person_id
           OR original.purpose <> NEW.purpose
           OR original.channel <> NEW.channel THEN
            RAISE EXCEPTION 'consent correction context mismatch' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS people_personcontactalias_owner_guard ON public.people_personcontactalias;
DROP TRIGGER IF EXISTS commercial_person_contact_guard ON public.commercial_person;
DROP FUNCTION IF EXISTS public.claridez_people_guard_contact_alias();
DROP FUNCTION IF EXISTS public.claridez_people_guard_person_contacts();
DROP FUNCTION IF EXISTS public.claridez_people_canonical_id(uuid, uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("people", "0002_privacy_merge_and_rls")]

    operations = [
        migrations.AddConstraint(
            model_name="person",
            constraint=models.UniqueConstraint(
                condition=models.Q(("email", ""), _negated=True),
                fields=("organization", "email"),
                name="commercial_person_org_email_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="person",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "email",
                        django.db.models.functions.text.Lower(
                            django.db.models.functions.text.Trim("email")
                        ),
                    )
                ),
                name="commercial_person_email_canonical",
            ),
        ),
        migrations.AddConstraint(
            model_name="personcontactalias",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("kind", "phone"),
                        (
                            "normalized_value__regex",
                            r"^\+593(?:[2-7][0-9]{7}|9[0-9]{8})$",
                        ),
                    ),
                    models.Q(
                        ("kind", "email"),
                        (
                            "normalized_value",
                            django.db.models.functions.text.Lower(
                                django.db.models.functions.text.Trim("normalized_value")
                            ),
                        ),
                        models.Q(("normalized_value", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="people_contactalias_value_canonical",
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
