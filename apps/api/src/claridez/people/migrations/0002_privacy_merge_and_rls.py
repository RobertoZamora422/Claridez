# ruff: noqa: E501

import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models

PEOPLE_SECURITY_FORWARD = r"""
ALTER TABLE public.people_personmerge
    ADD CONSTRAINT people_personmerge_tenant_source_fk
    FOREIGN KEY (organization_id, source_person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.people_personmerge
    ADD CONSTRAINT people_personmerge_tenant_target_fk
    FOREIGN KEY (organization_id, target_person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.people_personmerge
    ADD CONSTRAINT people_personmerge_tenant_actor_fk
    FOREIGN KEY (organization_id, merged_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.people_personcontactalias
    ADD CONSTRAINT people_contactalias_tenant_person_fk
    FOREIGN KEY (organization_id, person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.people_personcontactalias
    ADD CONSTRAINT people_contactalias_tenant_source_fk
    FOREIGN KEY (organization_id, source_person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.people_consentevent
    ADD CONSTRAINT people_consentevent_tenant_person_fk
    FOREIGN KEY (organization_id, person_id)
    REFERENCES public.commercial_person (organization_id, id);
ALTER TABLE public.people_consentevent
    ADD CONSTRAINT people_consentevent_tenant_actor_fk
    FOREIGN KEY (organization_id, recorded_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.people_consentevent
    ADD CONSTRAINT people_consentevent_tenant_correction_fk
    FOREIGN KEY (organization_id, corrects_id)
    REFERENCES public.people_consentevent (organization_id, id);

REVOKE ALL ON TABLE public.people_personmerge FROM PUBLIC;
REVOKE ALL ON TABLE public.people_personcontactalias FROM PUBLIC;
REVOKE ALL ON TABLE public.people_consentevent FROM PUBLIC;
GRANT SELECT, INSERT ON TABLE public.people_personmerge TO claridez_app;
GRANT SELECT, INSERT ON TABLE public.people_personcontactalias TO claridez_app;
GRANT SELECT, INSERT ON TABLE public.people_consentevent TO claridez_app;

ALTER TABLE public.people_personmerge ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_personmerge FORCE ROW LEVEL SECURITY;
ALTER TABLE public.people_personcontactalias ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_personcontactalias FORCE ROW LEVEL SECURITY;
ALTER TABLE public.people_consentevent ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_consentevent FORCE ROW LEVEL SECURITY;

CREATE POLICY people_personmerge_tenant_policy
ON public.people_personmerge AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY people_personcontactalias_tenant_policy
ON public.people_personcontactalias AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY people_consentevent_tenant_policy
ON public.people_consentevent AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());

CREATE FUNCTION public.claridez_people_reject_append_only_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'people evidence is append-only' USING ERRCODE = '23514';
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_reject_append_only_change() FROM PUBLIC;

CREATE TRIGGER people_personmerge_immutable
BEFORE UPDATE OR DELETE ON public.people_personmerge
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_reject_append_only_change();
CREATE TRIGGER people_personcontactalias_immutable
BEFORE UPDATE OR DELETE ON public.people_personcontactalias
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_reject_append_only_change();
CREATE TRIGGER people_consentevent_immutable
BEFORE UPDATE OR DELETE ON public.people_consentevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_reject_append_only_change();

CREATE FUNCTION public.claridez_people_guard_merge()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    source_revision_value integer;
    target_revision_value integer;
BEGIN
    PERFORM 1
    FROM public.commercial_person
    WHERE organization_id = NEW.organization_id
      AND id IN (NEW.source_person_id, NEW.target_person_id)
    ORDER BY id
    FOR UPDATE;

    SELECT revision INTO source_revision_value
    FROM public.commercial_person
    WHERE organization_id = NEW.organization_id AND id = NEW.source_person_id;
    SELECT revision INTO target_revision_value
    FROM public.commercial_person
    WHERE organization_id = NEW.organization_id AND id = NEW.target_person_id;

    IF source_revision_value IS NULL OR target_revision_value IS NULL THEN
        RAISE EXCEPTION 'person merge target is unavailable' USING ERRCODE = '23514';
    END IF;
    IF source_revision_value <> NEW.source_revision OR target_revision_value <> NEW.target_revision THEN
        RAISE EXCEPTION 'person merge revision is stale' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.people_personmerge
        WHERE organization_id = NEW.organization_id AND source_person_id = NEW.target_person_id
    ) THEN
        RAISE EXCEPTION 'person merge target must be canonical' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        WITH RECURSIVE path(person_id) AS (
            SELECT NEW.target_person_id
            UNION ALL
            SELECT merge.target_person_id
            FROM public.people_personmerge AS merge
            JOIN path ON merge.source_person_id = path.person_id
            WHERE merge.organization_id = NEW.organization_id
        )
        SELECT 1 FROM path WHERE person_id = NEW.source_person_id
    ) THEN
        RAISE EXCEPTION 'person merge cycle is not allowed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_guard_merge() FROM PUBLIC;

CREATE TRIGGER people_personmerge_guard
BEFORE INSERT ON public.people_personmerge
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_guard_merge();

CREATE FUNCTION public.claridez_people_require_canonical_person()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    PERFORM 1 FROM public.commercial_person
    WHERE organization_id = NEW.organization_id AND id = NEW.person_id
    FOR KEY SHARE;
    IF EXISTS (
        SELECT 1 FROM public.people_personmerge
        WHERE organization_id = NEW.organization_id AND source_person_id = NEW.person_id
    ) THEN
        RAISE EXCEPTION 'new relations require the canonical person' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_require_canonical_person() FROM PUBLIC;

CREATE TRIGGER commercial_eventrequest_canonical_person
BEFORE INSERT OR UPDATE OF person_id ON public.commercial_eventrequest
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_require_canonical_person();
CREATE TRIGGER people_consentevent_canonical_person
BEFORE INSERT OR UPDATE OF person_id ON public.people_consentevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_require_canonical_person();

CREATE FUNCTION public.claridez_people_guard_person_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.people_personmerge
        WHERE organization_id = OLD.organization_id AND source_person_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'merged people cannot be modified' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_people_guard_person_update() FROM PUBLIC;
CREATE TRIGGER commercial_person_merged_immutable
BEFORE UPDATE ON public.commercial_person
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_guard_person_update();

CREATE FUNCTION public.claridez_people_guard_consent_correction()
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
REVOKE ALL ON FUNCTION public.claridez_people_guard_consent_correction() FROM PUBLIC;
CREATE TRIGGER people_consentevent_correction_guard
BEFORE INSERT ON public.people_consentevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_people_guard_consent_correction();
"""

PEOPLE_SECURITY_REVERSE = r"""
DROP TRIGGER IF EXISTS people_consentevent_correction_guard ON public.people_consentevent;
DROP FUNCTION IF EXISTS public.claridez_people_guard_consent_correction();
DROP TRIGGER IF EXISTS commercial_person_merged_immutable ON public.commercial_person;
DROP FUNCTION IF EXISTS public.claridez_people_guard_person_update();
DROP TRIGGER IF EXISTS people_consentevent_canonical_person ON public.people_consentevent;
DROP TRIGGER IF EXISTS commercial_eventrequest_canonical_person ON public.commercial_eventrequest;
DROP FUNCTION IF EXISTS public.claridez_people_require_canonical_person();
DROP TRIGGER IF EXISTS people_personmerge_guard ON public.people_personmerge;
DROP FUNCTION IF EXISTS public.claridez_people_guard_merge();
DROP TRIGGER IF EXISTS people_consentevent_immutable ON public.people_consentevent;
DROP TRIGGER IF EXISTS people_personcontactalias_immutable ON public.people_personcontactalias;
DROP TRIGGER IF EXISTS people_personmerge_immutable ON public.people_personmerge;
DROP FUNCTION IF EXISTS public.claridez_people_reject_append_only_change();
DROP POLICY IF EXISTS people_consentevent_tenant_policy ON public.people_consentevent;
DROP POLICY IF EXISTS people_personcontactalias_tenant_policy ON public.people_personcontactalias;
DROP POLICY IF EXISTS people_personmerge_tenant_policy ON public.people_personmerge;
ALTER TABLE public.people_consentevent NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.people_consentevent DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_personcontactalias NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.people_personcontactalias DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_personmerge NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.people_personmerge DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.people_consentevent FROM claridez_app;
REVOKE ALL ON TABLE public.people_personcontactalias FROM claridez_app;
REVOKE ALL ON TABLE public.people_personmerge FROM claridez_app;
ALTER TABLE public.people_consentevent DROP CONSTRAINT IF EXISTS people_consentevent_tenant_correction_fk;
ALTER TABLE public.people_consentevent DROP CONSTRAINT IF EXISTS people_consentevent_tenant_actor_fk;
ALTER TABLE public.people_consentevent DROP CONSTRAINT IF EXISTS people_consentevent_tenant_person_fk;
ALTER TABLE public.people_personcontactalias DROP CONSTRAINT IF EXISTS people_contactalias_tenant_source_fk;
ALTER TABLE public.people_personcontactalias DROP CONSTRAINT IF EXISTS people_contactalias_tenant_person_fk;
ALTER TABLE public.people_personmerge DROP CONSTRAINT IF EXISTS people_personmerge_tenant_actor_fk;
ALTER TABLE public.people_personmerge DROP CONSTRAINT IF EXISTS people_personmerge_tenant_target_fk;
ALTER TABLE public.people_personmerge DROP CONSTRAINT IF EXISTS people_personmerge_tenant_source_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0001_adopt_person_state"),
        ("commercial", "0005_people_state_and_event_history"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsentEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("purpose", models.CharField(max_length=80)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("email", "Correo"),
                            ("whatsapp", "WhatsApp"),
                            ("phone", "Teléfono"),
                            ("other", "Otro"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("grant", "Concesión"),
                            ("revoke", "Revocación"),
                            ("correction", "Rectificación"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        choices=[("granted", "Concedido"), ("revoked", "Revocado")], max_length=16
                    ),
                ),
                ("source", models.CharField(max_length=80)),
                ("occurred_at", models.DateTimeField()),
                ("evidence_reference", models.CharField(max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "corrects",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="corrections",
                        to="people.consentevent",
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
                        related_name="consent_events",
                        to="people.person",
                    ),
                ),
                (
                    "recorded_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recorded_consents",
                        to="organizations.membership",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="people_consentevent_org_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("purpose", django.db.models.functions.text.Trim("purpose")),
                            models.Q(("purpose", ""), _negated=True),
                        ),
                        name="people_consentevent_purpose_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source", django.db.models.functions.text.Trim("source")),
                            models.Q(("source", ""), _negated=True),
                        ),
                        name="people_consentevent_source_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "evidence_reference",
                                django.db.models.functions.text.Trim("evidence_reference"),
                            ),
                            models.Q(("evidence_reference", ""), _negated=True),
                        ),
                        name="people_consentevent_evidence_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("channel__in", ["email", "whatsapp", "phone", "other"])
                        ),
                        name="people_consentevent_channel_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("event_type__in", ["grant", "revoke", "correction"])),
                        name="people_consentevent_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("decision__in", ["granted", "revoked"])),
                        name="people_consentevent_decision_valid",
                    ),
                ]
            },
        ),
        migrations.CreateModel(
            name="PersonContactAlias",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("source_revision", models.PositiveIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[("phone", "Teléfono"), ("email", "Correo")], max_length=8
                    ),
                ),
                ("normalized_value", models.CharField(max_length=254)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
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
                        related_name="contact_aliases",
                        to="people.person",
                    ),
                ),
                (
                    "source_person",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="provided_contact_aliases",
                        to="people.person",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="people_contactalias_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "kind", "normalized_value"),
                        name="people_contactalias_org_kind_value_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("source_revision__gte", 1)),
                        name="people_contactalias_revision_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("kind__in", ["phone", "email"])),
                        name="people_contactalias_kind_valid",
                    ),
                ]
            },
        ),
        migrations.CreateModel(
            name="PersonMerge",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("source_revision", models.PositiveIntegerField()),
                ("target_revision", models.PositiveIntegerField()),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "merged_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="person_merges",
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
                    "source_person",
                    models.OneToOneField(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="merge_as_source",
                        to="people.person",
                    ),
                ),
                (
                    "target_person",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="merge_sources",
                        to="people.person",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="people_personmerge_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "source_person"),
                        name="people_personmerge_org_source_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "idempotency_key"),
                        name="people_personmerge_org_idempotency_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source_person", models.F("target_person")), _negated=True
                        ),
                        name="people_personmerge_distinct_people",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source_revision__gte", 1), ("target_revision__gte", 1)
                        ),
                        name="people_personmerge_revisions_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("reason", django.db.models.functions.text.Trim("reason")),
                            models.Q(("reason", ""), _negated=True),
                        ),
                        name="people_personmerge_reason_canonical",
                    ),
                ]
            },
        ),
        migrations.RunSQL(PEOPLE_SECURITY_FORWARD, PEOPLE_SECURITY_REVERSE),
    ]
