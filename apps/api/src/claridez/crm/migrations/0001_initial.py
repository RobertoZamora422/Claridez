# ruff: noqa: E501

import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models

CRM_SECURITY_FORWARD = r"""
ALTER TABLE public.crm_interaction
    ADD CONSTRAINT crm_interaction_tenant_person_fk
    FOREIGN KEY (organization_id, person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.crm_interaction
    ADD CONSTRAINT crm_interaction_tenant_request_fk
    FOREIGN KEY (organization_id, event_request_id)
    REFERENCES public.commercial_eventrequest (organization_id, id);
ALTER TABLE public.crm_interaction
    ADD CONSTRAINT crm_interaction_tenant_responsible_fk
    FOREIGN KEY (organization_id, responsible_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.crm_interaction
    ADD CONSTRAINT crm_interaction_tenant_recorder_fk
    FOREIGN KEY (organization_id, recorded_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.crm_interaction
    ADD CONSTRAINT crm_interaction_tenant_correction_fk
    FOREIGN KEY (organization_id, correction_of_id)
    REFERENCES public.crm_interaction (organization_id, id);

ALTER TABLE public.crm_followuptask
    ADD CONSTRAINT crm_task_tenant_person_fk
    FOREIGN KEY (organization_id, person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.crm_followuptask
    ADD CONSTRAINT crm_task_tenant_request_fk
    FOREIGN KEY (organization_id, event_request_id)
    REFERENCES public.commercial_eventrequest (organization_id, id);
ALTER TABLE public.crm_followuptask
    ADD CONSTRAINT crm_task_tenant_responsible_fk
    FOREIGN KEY (organization_id, responsible_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.crm_followuptask
    ADD CONSTRAINT crm_task_tenant_completed_by_fk
    FOREIGN KEY (organization_id, completed_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.crm_followuptask
    ADD CONSTRAINT crm_task_tenant_created_by_fk
    FOREIGN KEY (organization_id, created_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);

ALTER TABLE public.crm_followuptaskhistory
    ADD CONSTRAINT crm_taskhistory_tenant_task_fk
    FOREIGN KEY (organization_id, task_id)
    REFERENCES public.crm_followuptask (organization_id, id);
ALTER TABLE public.crm_followuptaskhistory
    ADD CONSTRAINT crm_taskhistory_tenant_responsible_fk
    FOREIGN KEY (organization_id, responsible_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.crm_followuptaskhistory
    ADD CONSTRAINT crm_taskhistory_tenant_actor_fk
    FOREIGN KEY (organization_id, changed_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);

REVOKE ALL ON TABLE public.crm_interaction FROM PUBLIC;
REVOKE ALL ON TABLE public.crm_followuptask FROM PUBLIC;
REVOKE ALL ON TABLE public.crm_followuptaskhistory FROM PUBLIC;
GRANT SELECT, INSERT ON TABLE public.crm_interaction TO claridez_app;
GRANT SELECT, INSERT, UPDATE ON TABLE public.crm_followuptask TO claridez_app;
GRANT SELECT, INSERT ON TABLE public.crm_followuptaskhistory TO claridez_app;

ALTER TABLE public.crm_interaction ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_interaction FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptask ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptask FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptaskhistory ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptaskhistory FORCE ROW LEVEL SECURITY;

CREATE POLICY crm_interaction_tenant_policy ON public.crm_interaction
AS PERMISSIVE FOR ALL TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY crm_followuptask_tenant_policy ON public.crm_followuptask
AS PERMISSIVE FOR ALL TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY crm_followuptaskhistory_tenant_policy ON public.crm_followuptaskhistory
AS PERMISSIVE FOR ALL TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());

CREATE FUNCTION public.claridez_crm_reject_append_only_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'crm evidence is append-only' USING ERRCODE = '23514';
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_crm_reject_append_only_change() FROM PUBLIC;
CREATE TRIGGER crm_interaction_immutable
BEFORE UPDATE OR DELETE ON public.crm_interaction
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_reject_append_only_change();
CREATE TRIGGER crm_taskhistory_immutable
BEFORE UPDATE OR DELETE ON public.crm_followuptaskhistory
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_reject_append_only_change();

CREATE FUNCTION public.claridez_crm_guard_link_context()
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

CREATE FUNCTION public.claridez_crm_guard_interaction_correction()
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

CREATE TRIGGER crm_interaction_canonical_person
BEFORE INSERT OR UPDATE OF person_id ON public.crm_interaction
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_require_canonical_person();
CREATE TRIGGER crm_task_canonical_person
BEFORE INSERT OR UPDATE OF person_id ON public.crm_followuptask
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_require_canonical_person();
CREATE TRIGGER crm_interaction_link_guard
BEFORE INSERT ON public.crm_interaction
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_guard_link_context();
CREATE TRIGGER crm_interaction_correction_guard
BEFORE INSERT ON public.crm_interaction
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_guard_interaction_correction();
CREATE TRIGGER crm_task_link_guard
BEFORE INSERT OR UPDATE OF person_id, event_request_id ON public.crm_followuptask
FOR EACH ROW EXECUTE FUNCTION public.claridez_crm_guard_link_context();

CREATE FUNCTION public.claridez_capture_crm_task_history()
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
REVOKE ALL ON FUNCTION public.claridez_capture_crm_task_history() FROM PUBLIC;
CREATE TRIGGER crm_task_history_capture
AFTER INSERT OR UPDATE ON public.crm_followuptask
FOR EACH ROW EXECUTE FUNCTION public.claridez_capture_crm_task_history();
"""

CRM_SECURITY_REVERSE = r"""
DROP TRIGGER IF EXISTS crm_task_history_capture ON public.crm_followuptask;
DROP FUNCTION IF EXISTS public.claridez_capture_crm_task_history();
DROP TRIGGER IF EXISTS crm_task_link_guard ON public.crm_followuptask;
DROP TRIGGER IF EXISTS crm_interaction_correction_guard ON public.crm_interaction;
DROP TRIGGER IF EXISTS crm_interaction_link_guard ON public.crm_interaction;
DROP TRIGGER IF EXISTS crm_task_canonical_person ON public.crm_followuptask;
DROP TRIGGER IF EXISTS crm_interaction_canonical_person ON public.crm_interaction;
DROP FUNCTION IF EXISTS public.claridez_crm_guard_interaction_correction();
DROP FUNCTION IF EXISTS public.claridez_crm_guard_link_context();
DROP TRIGGER IF EXISTS crm_taskhistory_immutable ON public.crm_followuptaskhistory;
DROP TRIGGER IF EXISTS crm_interaction_immutable ON public.crm_interaction;
DROP FUNCTION IF EXISTS public.claridez_crm_reject_append_only_change();
DROP POLICY IF EXISTS crm_followuptaskhistory_tenant_policy ON public.crm_followuptaskhistory;
DROP POLICY IF EXISTS crm_followuptask_tenant_policy ON public.crm_followuptask;
DROP POLICY IF EXISTS crm_interaction_tenant_policy ON public.crm_interaction;
ALTER TABLE public.crm_followuptaskhistory NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptaskhistory DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptask NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_followuptask DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_interaction NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.crm_interaction DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.crm_followuptaskhistory FROM claridez_app;
REVOKE ALL ON TABLE public.crm_followuptask FROM claridez_app;
REVOKE ALL ON TABLE public.crm_interaction FROM claridez_app;
ALTER TABLE public.crm_followuptaskhistory DROP CONSTRAINT IF EXISTS crm_taskhistory_tenant_actor_fk;
ALTER TABLE public.crm_followuptaskhistory DROP CONSTRAINT IF EXISTS crm_taskhistory_tenant_responsible_fk;
ALTER TABLE public.crm_followuptaskhistory DROP CONSTRAINT IF EXISTS crm_taskhistory_tenant_task_fk;
ALTER TABLE public.crm_followuptask DROP CONSTRAINT IF EXISTS crm_task_tenant_created_by_fk;
ALTER TABLE public.crm_followuptask DROP CONSTRAINT IF EXISTS crm_task_tenant_completed_by_fk;
ALTER TABLE public.crm_followuptask DROP CONSTRAINT IF EXISTS crm_task_tenant_responsible_fk;
ALTER TABLE public.crm_followuptask DROP CONSTRAINT IF EXISTS crm_task_tenant_request_fk;
ALTER TABLE public.crm_followuptask DROP CONSTRAINT IF EXISTS crm_task_tenant_person_fk;
ALTER TABLE public.crm_interaction DROP CONSTRAINT IF EXISTS crm_interaction_tenant_correction_fk;
ALTER TABLE public.crm_interaction DROP CONSTRAINT IF EXISTS crm_interaction_tenant_recorder_fk;
ALTER TABLE public.crm_interaction DROP CONSTRAINT IF EXISTS crm_interaction_tenant_responsible_fk;
ALTER TABLE public.crm_interaction DROP CONSTRAINT IF EXISTS crm_interaction_tenant_request_fk;
ALTER TABLE public.crm_interaction DROP CONSTRAINT IF EXISTS crm_interaction_tenant_person_fk;
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("commercial", "0005_people_state_and_event_history"),
        ("people", "0002_privacy_merge_and_rls"),
        ("organizations", "0004_venues_and_spaces"),
    ]

    operations = [
        migrations.CreateModel(
            name="Interaction",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("phone_call", "Llamada"),
                            ("whatsapp", "WhatsApp"),
                            ("email", "Correo"),
                            ("in_person", "Presencial"),
                            ("social_network", "Red social"),
                            ("other", "Otro"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "direction",
                    models.CharField(
                        choices=[("inbound", "Entrante"), ("outbound", "Saliente")], max_length=12
                    ),
                ),
                ("occurred_at", models.DateTimeField()),
                ("summary", models.CharField(max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "correction_of",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="corrections",
                        to="crm.interaction",
                    ),
                ),
                (
                    "event_request",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_interactions",
                        to="commercial.eventrequest",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "person",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_interactions",
                        to="people.person",
                    ),
                ),
                (
                    "recorded_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recorded_crm_interactions",
                        to="organizations.membership",
                    ),
                ),
                (
                    "responsible_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="responsible_crm_interactions",
                        to="organizations.membership",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-created_at", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="crm_interaction_org_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "channel__in",
                                [
                                    "phone_call",
                                    "whatsapp",
                                    "email",
                                    "in_person",
                                    "social_network",
                                    "other",
                                ],
                            )
                        ),
                        name="crm_interaction_channel_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("direction__in", ["inbound", "outbound"])),
                        name="crm_interaction_direction_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("summary", django.db.models.functions.text.Trim("summary")),
                            models.Q(("summary", ""), _negated=True),
                        ),
                        name="crm_interaction_summary_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("id", models.F("correction_of")), _negated=True),
                        name="crm_interaction_not_self_correction",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="FollowUpTask",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("title", models.CharField(max_length=180)),
                ("due_at", models.DateTimeField()),
                ("next_contact_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Pendiente"),
                            ("completed", "Completada"),
                            ("cancelled", "Cancelada"),
                        ],
                        default="open",
                        max_length=12,
                    ),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "completed_by_membership",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="completed_crm_tasks",
                        to="organizations.membership",
                    ),
                ),
                (
                    "created_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_crm_tasks",
                        to="organizations.membership",
                    ),
                ),
                (
                    "event_request",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_tasks",
                        to="commercial.eventrequest",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "person",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_tasks",
                        to="people.person",
                    ),
                ),
                (
                    "responsible_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_tasks",
                        to="organizations.membership",
                    ),
                ),
            ],
            options={
                "ordering": ["due_at", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="crm_task_org_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("title", django.db.models.functions.text.Trim("title")),
                            models.Q(("title", ""), _negated=True),
                        ),
                        name="crm_task_title_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("status__in", ["open", "completed", "cancelled"])),
                        name="crm_task_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)), name="crm_task_revision_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("completed_at__isnull", False),
                                ("completed_by_membership__isnull", False),
                                ("status", "completed"),
                            ),
                            models.Q(
                                ("completed_at__isnull", True),
                                ("completed_by_membership__isnull", True),
                                ("status__in", ["open", "cancelled"]),
                            ),
                            _connector="OR",
                        ),
                        name="crm_task_completed_evidence",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="FollowUpTaskHistory",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("created", "Creación"),
                            ("updated", "Actualización"),
                            ("completed", "Finalización"),
                            ("cancelled", "Cancelación"),
                        ],
                        max_length=12,
                    ),
                ),
                ("revision", models.PositiveIntegerField()),
                ("title", models.CharField(max_length=180)),
                ("due_at", models.DateTimeField()),
                ("next_contact_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Pendiente"),
                            ("completed", "Completada"),
                            ("cancelled", "Cancelada"),
                        ],
                        max_length=12,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "changed_by_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_task_history_actions",
                        to="organizations.membership",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "responsible_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_task_history_responsibilities",
                        to="organizations.membership",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="history",
                        to="crm.followuptask",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="crm_taskhistory_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "task", "revision"),
                        name="crm_taskhistory_org_task_revision_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)),
                        name="crm_taskhistory_revision_positive",
                    ),
                ],
            },
        ),
        migrations.RunSQL(CRM_SECURITY_FORWARD, CRM_SECURITY_REVERSE),
    ]
