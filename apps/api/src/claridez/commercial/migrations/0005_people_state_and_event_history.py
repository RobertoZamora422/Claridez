# ruff: noqa: E501

import uuid

import django.db.models.deletion
from django.db import migrations, models


def backfill_cutover_state(apps, schema_editor):  # type: ignore[no-untyped-def]
    EventRequest = apps.get_model("commercial", "EventRequest")
    EventRequestHistory = apps.get_model("commercial", "EventRequestHistory")
    Organization = apps.get_model("organizations", "Organization")
    alias = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        previous = cursor.fetchone()[0] or ""
        try:
            for organization_id in Organization.objects.using(alias).values_list("id", flat=True):
                cursor.execute(
                    "SELECT set_config('claridez.organization_id', %s, true)",
                    [str(organization_id)],
                )
                rows = (
                    EventRequest.objects.using(alias)
                    .filter(organization_id=organization_id)
                    .order_by("id")
                    .iterator(chunk_size=500)
                )
                EventRequestHistory.objects.using(alias).bulk_create(
                    [
                        EventRequestHistory(
                            organization_id=row.organization_id,
                            event_request_id=row.pk,
                            kind="cutover_state",
                            status=row.status,
                            request_revision=row.revision,
                            origin=row.origin,
                            origin_detail=row.origin_detail,
                            responsible_membership_id=row.responsible_membership_id,
                            actor_membership_id=None,
                            occurred_at=None,
                            provenance="cutover_snapshot",
                            reason=row.closed_reason,
                        )
                        for row in rows
                    ],
                    batch_size=500,
                )
        finally:
            cursor.execute("SELECT set_config('claridez.organization_id', %s, true)", [previous])


HISTORY_FORWARD = r"""
ALTER TABLE public.commercial_eventrequest NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.commercial_eventrequesthistory
    ADD CONSTRAINT commercial_requesthistory_tenant_request_fk
    FOREIGN KEY (organization_id, event_request_id)
    REFERENCES public.commercial_eventrequest (organization_id, id);
ALTER TABLE public.commercial_eventrequesthistory
    ADD CONSTRAINT commercial_requesthistory_tenant_responsible_fk
    FOREIGN KEY (organization_id, responsible_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.commercial_eventrequesthistory
    ADD CONSTRAINT commercial_requesthistory_tenant_actor_fk
    FOREIGN KEY (organization_id, actor_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.commercial_eventrequest FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.commercial_eventrequesthistory FROM PUBLIC;
GRANT SELECT, INSERT ON TABLE public.commercial_eventrequesthistory TO claridez_app;
ALTER TABLE public.commercial_eventrequesthistory ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.commercial_eventrequesthistory FORCE ROW LEVEL SECURITY;
CREATE POLICY commercial_eventrequesthistory_tenant_policy
ON public.commercial_eventrequesthistory AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());

CREATE FUNCTION public.claridez_reject_event_request_history_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'event request history is append-only' USING ERRCODE = '23514';
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_reject_event_request_history_change() FROM PUBLIC;

CREATE TRIGGER commercial_eventrequesthistory_immutable
BEFORE UPDATE OR DELETE ON public.commercial_eventrequesthistory
FOR EACH ROW EXECUTE FUNCTION public.claridez_reject_event_request_history_change();

CREATE FUNCTION public.claridez_capture_event_request_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    audit_membership uuid;
    history_kind varchar(20);
BEGIN
    audit_membership := NULLIF(current_setting('claridez.membership_id', true), '')::uuid;
    IF TG_OP = 'INSERT' THEN
        history_kind := 'created';
    ELSIF OLD.status IS DISTINCT FROM NEW.status THEN
        history_kind := 'status_changed';
    ELSE
        history_kind := 'updated';
    END IF;

    INSERT INTO public.commercial_eventrequesthistory (
        id, organization_id, event_request_id, kind, status, request_revision,
        origin, origin_detail, responsible_membership_id, actor_membership_id,
        occurred_at, provenance, reason, created_at
    ) VALUES (
        gen_random_uuid(), NEW.organization_id, NEW.id, history_kind, NEW.status, NEW.revision,
        NEW.origin, NEW.origin_detail, NEW.responsible_membership_id, audit_membership,
        CURRENT_TIMESTAMP, 'database', NEW.closed_reason, CURRENT_TIMESTAMP
    );
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_capture_event_request_history() FROM PUBLIC;

CREATE TRIGGER commercial_eventrequest_history_capture
AFTER INSERT OR UPDATE OF status, revision, origin, origin_detail, responsible_membership_id, closed_reason
ON public.commercial_eventrequest
FOR EACH ROW EXECUTE FUNCTION public.claridez_capture_event_request_history();
"""

HISTORY_REVERSE = r"""
DROP TRIGGER IF EXISTS commercial_eventrequest_history_capture ON public.commercial_eventrequest;
DROP FUNCTION IF EXISTS public.claridez_capture_event_request_history();
DROP TRIGGER IF EXISTS commercial_eventrequesthistory_immutable ON public.commercial_eventrequesthistory;
DROP FUNCTION IF EXISTS public.claridez_reject_event_request_history_change();
DROP POLICY IF EXISTS commercial_eventrequesthistory_tenant_policy ON public.commercial_eventrequesthistory;
ALTER TABLE public.commercial_eventrequesthistory NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.commercial_eventrequesthistory DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.commercial_eventrequesthistory FROM claridez_app;
ALTER TABLE public.commercial_eventrequesthistory DROP CONSTRAINT IF EXISTS commercial_requesthistory_tenant_actor_fk;
ALTER TABLE public.commercial_eventrequesthistory DROP CONSTRAINT IF EXISTS commercial_requesthistory_tenant_responsible_fk;
ALTER TABLE public.commercial_eventrequesthistory DROP CONSTRAINT IF EXISTS commercial_requesthistory_tenant_request_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0004_multi_space_and_catalog"),
        ("people", "0001_adopt_person_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="eventrequest",
                    name="person",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="event_requests",
                        to="people.person",
                    ),
                ),
                migrations.DeleteModel(name="PersonRevision"),
                migrations.DeleteModel(name="Person"),
            ],
        ),
        migrations.CreateModel(
            name="EventRequestHistory",
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
                            ("cutover_state", "Estado existente al corte"),
                            ("created", "Creación"),
                            ("updated", "Actualización"),
                            ("status_changed", "Cambio de estado"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "Nueva"),
                            ("quoted", "Cotizada"),
                            ("accepted", "Aceptada"),
                            ("confirmed", "Confirmada"),
                            ("closed_lost", "Perdida"),
                            ("cancelled", "Cancelada"),
                        ],
                        max_length=20,
                    ),
                ),
                ("request_revision", models.PositiveIntegerField()),
                (
                    "origin",
                    models.CharField(
                        choices=[
                            ("whatsapp", "WhatsApp"),
                            ("phone_call", "Llamada"),
                            ("social_network", "Red social"),
                            ("referral", "Referido"),
                            ("walk_in", "Visita"),
                            ("website", "Sitio web"),
                            ("other", "Otro"),
                        ],
                        max_length=24,
                    ),
                ),
                ("origin_detail", models.CharField(blank=True, max_length=160)),
                ("occurred_at", models.DateTimeField(blank=True, null=True)),
                (
                    "provenance",
                    models.CharField(
                        choices=[
                            ("cutover_snapshot", "Snapshot de corte"),
                            ("database", "Registro de base de datos"),
                        ],
                        max_length=24,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor_membership",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="event_request_history_actions",
                        to="organizations.membership",
                    ),
                ),
                (
                    "event_request",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="history",
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
                    "responsible_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="request_history_responsibilities",
                        to="organizations.membership",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"),
                        name="commercial_requesthistory_org_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("request_revision__gte", 1)),
                        name="commercial_requesthistory_revision_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "kind__in",
                                ["cutover_state", "created", "updated", "status_changed"],
                            )
                        ),
                        name="commercial_requesthistory_kind_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "status__in",
                                [
                                    "new",
                                    "quoted",
                                    "accepted",
                                    "confirmed",
                                    "closed_lost",
                                    "cancelled",
                                ],
                            )
                        ),
                        name="commercial_requesthistory_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("provenance__in", ["cutover_snapshot", "database"])),
                        name="commercial_requesthistory_provenance_valid",
                    ),
                ],
            },
        ),
        migrations.RunPython(backfill_cutover_state, migrations.RunPython.noop),
        migrations.RunSQL(HISTORY_FORWARD, HISTORY_REVERSE),
    ]
