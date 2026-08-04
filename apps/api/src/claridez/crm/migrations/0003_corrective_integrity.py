# ruff: noqa: E501

import django.db.models.functions.text
from django.db import migrations, models

LEGACY_REASON_BACKFILL = r"""
ALTER TABLE public.crm_followuptask NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptaskhistory NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptask DISABLE TRIGGER crm_task_history_capture;
ALTER TABLE public.crm_followuptaskhistory DISABLE TRIGGER crm_taskhistory_immutable;

UPDATE public.crm_followuptask
SET cancellation_reason_unavailable = TRUE
WHERE status = 'cancelled' AND cancellation_reason = '';

UPDATE public.crm_followuptaskhistory
SET reason_unavailable = TRUE
WHERE kind = 'cancelled' AND reason = '';

ALTER TABLE public.crm_followuptaskhistory ENABLE TRIGGER crm_taskhistory_immutable;
ALTER TABLE public.crm_followuptask ENABLE TRIGGER crm_task_history_capture;
ALTER TABLE public.crm_followuptaskhistory FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptask FORCE ROW LEVEL SECURITY;
"""

FORWARD = r"""
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
           OR public.claridez_people_canonical_id(original.organization_id, original.person_id)
              IS DISTINCT FROM
              public.claridez_people_canonical_id(NEW.organization_id, NEW.person_id)
           OR original.event_request_id IS DISTINCT FROM NEW.event_request_id THEN
            RAISE EXCEPTION 'interaction correction context mismatch' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_crm_guard_interaction_correction() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_crm_guard_task_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.revision <> 1
           OR NEW.status <> 'open'
           OR NEW.cancellation_reason <> ''
           OR NEW.cancellation_reason_unavailable THEN
            RAISE EXCEPTION 'new crm task must start open at revision one' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.person_id IS DISTINCT FROM OLD.person_id
       OR NEW.event_request_id IS DISTINCT FROM OLD.event_request_id
       OR NEW.created_by_membership_id IS DISTINCT FROM OLD.created_by_membership_id
       OR NEW.cancellation_reason_unavailable IS DISTINCT FROM OLD.cancellation_reason_unavailable
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'crm task identity and context are immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.status <> 'open' THEN
        RAISE EXCEPTION 'closed crm task is immutable' USING ERRCODE = '23514';
    END IF;

    IF NEW.title IS NOT DISTINCT FROM OLD.title
       AND NEW.due_at IS NOT DISTINCT FROM OLD.due_at
       AND NEW.next_contact_at IS NOT DISTINCT FROM OLD.next_contact_at
       AND NEW.status IS NOT DISTINCT FROM OLD.status
       AND NEW.responsible_membership_id IS NOT DISTINCT FROM OLD.responsible_membership_id
       AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at
       AND NEW.completed_by_membership_id IS NOT DISTINCT FROM OLD.completed_by_membership_id
       AND NEW.cancellation_reason IS NOT DISTINCT FROM OLD.cancellation_reason THEN
        RETURN NULL;
    END IF;

    IF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'crm task revision must advance exactly once' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_crm_guard_task_change() FROM PUBLIC;
DROP TRIGGER IF EXISTS crm_task_change_guard ON public.crm_followuptask;
CREATE TRIGGER crm_task_change_guard
BEFORE INSERT OR UPDATE ON public.crm_followuptask
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_guard_task_change();

CREATE OR REPLACE FUNCTION public.claridez_capture_crm_task_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    audit_membership uuid;
    history_kind varchar(12);
    history_reason varchar(500);
BEGIN
    audit_membership := COALESCE(
        NULLIF(current_setting('claridez.membership_id', true), '')::uuid,
        NEW.completed_by_membership_id,
        NEW.created_by_membership_id
    );
    IF TG_OP = 'INSERT' THEN
        history_kind := 'created';
    ELSIF NEW.status = 'completed' AND OLD.status IS DISTINCT FROM NEW.status THEN
        history_kind := 'completed';
    ELSIF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM NEW.status THEN
        history_kind := 'cancelled';
    ELSE
        history_kind := 'updated';
    END IF;
    history_reason := CASE
        WHEN history_kind = 'cancelled' THEN NEW.cancellation_reason
        ELSE ''
    END;

    INSERT INTO public.crm_followuptaskhistory (
        id, organization_id, task_id, kind, revision, title, due_at,
        next_contact_at, status, responsible_membership_id,
        changed_by_membership_id, reason, reason_unavailable, created_at
    ) VALUES (
        gen_random_uuid(), NEW.organization_id, NEW.id, history_kind, NEW.revision,
        NEW.title, NEW.due_at, NEW.next_contact_at, NEW.status,
        NEW.responsible_membership_id, audit_membership, history_reason, FALSE, CURRENT_TIMESTAMP
    );
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_capture_crm_task_history() FROM PUBLIC;
"""

REVERSE = r"""
DROP TRIGGER IF EXISTS crm_task_change_guard ON public.crm_followuptask;
DROP FUNCTION IF EXISTS public.claridez_crm_guard_task_change();

CREATE OR REPLACE FUNCTION public.claridez_capture_crm_task_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    audit_membership uuid;
    history_kind varchar(12);
BEGIN
    audit_membership := COALESCE(
        NULLIF(current_setting('claridez.membership_id', true), '')::uuid,
        NEW.completed_by_membership_id,
        NEW.created_by_membership_id
    );
    IF TG_OP = 'INSERT' THEN
        history_kind := 'created';
    ELSIF NEW.status = 'completed' AND OLD.status IS DISTINCT FROM NEW.status THEN
        history_kind := 'completed';
    ELSIF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM NEW.status THEN
        history_kind := 'cancelled';
    ELSE
        history_kind := 'updated';
    END IF;

    INSERT INTO public.crm_followuptaskhistory (
        id, organization_id, task_id, kind, revision, title, due_at,
        next_contact_at, status, responsible_membership_id,
        changed_by_membership_id, reason, created_at
    ) VALUES (
        gen_random_uuid(), NEW.organization_id, NEW.id, history_kind, NEW.revision,
        NEW.title, NEW.due_at, NEW.next_contact_at, NEW.status,
        NEW.responsible_membership_id, audit_membership, '', CURRENT_TIMESTAMP
    );
    RETURN NEW;
END;
$function$;

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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0006_repair_cutover_history"),
        ("crm", "0002_interaction_correction_guard"),
        ("people", "0003_contact_history_and_consent_integrity"),
    ]

    operations = [
        migrations.AddField(
            model_name="followuptask",
            name="cancellation_reason",
            field=models.CharField(blank=True, default="", max_length=500),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="followuptask",
            name="cancellation_reason_unavailable",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="followuptaskhistory",
            name="reason_unavailable",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.RunSQL(LEGACY_REASON_BACKFILL, migrations.RunSQL.noop),
        migrations.AddConstraint(
            model_name="followuptask",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        (
                            "cancellation_reason",
                            django.db.models.functions.text.Trim("cancellation_reason"),
                        ),
                        ("cancellation_reason_unavailable", False),
                        ("status", "cancelled"),
                        models.Q(("cancellation_reason", ""), _negated=True),
                    ),
                    models.Q(
                        ("cancellation_reason", ""),
                        ("cancellation_reason_unavailable", True),
                        ("status", "cancelled"),
                    ),
                    models.Q(
                        ("cancellation_reason", ""),
                        ("cancellation_reason_unavailable", False),
                        ("status__in", ["open", "completed"]),
                    ),
                    _connector="OR",
                ),
                name="crm_task_cancellation_reason",
            ),
        ),
        migrations.AddConstraint(
            model_name="followuptaskhistory",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("kind", "cancelled"),
                        ("reason", django.db.models.functions.text.Trim("reason")),
                        ("reason_unavailable", False),
                        models.Q(("reason", ""), _negated=True),
                    ),
                    models.Q(("kind", "cancelled"), ("reason", ""), ("reason_unavailable", True)),
                    models.Q(
                        ("kind__in", ["created", "updated", "completed"]),
                        ("reason", ""),
                        ("reason_unavailable", False),
                    ),
                    _connector="OR",
                ),
                name="crm_taskhistory_reason_matches_kind",
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
