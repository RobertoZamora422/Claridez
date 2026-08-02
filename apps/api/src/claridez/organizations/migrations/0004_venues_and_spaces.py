import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


def create_primary_venues_and_spaces(apps, schema_editor):  # type: ignore[no-untyped-def]
    organization_model = apps.get_model("organizations", "Organization")
    venue_model = apps.get_model("organizations", "Venue")
    space_model = apps.get_model("organizations", "Space")
    for organization_id in organization_model.objects.values_list("pk", flat=True):
        venue_id = uuid.uuid5(organization_id, "claridez:venue:primary")
        space_id = uuid.uuid5(organization_id, "claridez:space:primary")
        venue_model.objects.create(
            id=venue_id,
            organization_id=organization_id,
            name="Sede principal",
            is_primary=True,
            is_active=True,
        )
        space_model.objects.create(
            id=space_id,
            organization_id=organization_id,
            venue_id=venue_id,
            name="Espacio principal",
            is_primary=True,
            is_active=True,
        )


TENANT_SECURITY_FORWARD = r"""
ALTER TABLE public.organizations_space
    ADD CONSTRAINT organizations_space_tenant_venue_fk
    FOREIGN KEY (organization_id, venue_id)
    REFERENCES public.organizations_venue (organization_id, id);

REVOKE ALL ON TABLE public.organizations_venue FROM PUBLIC;
REVOKE ALL ON TABLE public.organizations_space FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON TABLE public.organizations_venue TO claridez_app;
GRANT SELECT, INSERT, UPDATE ON TABLE public.organizations_space TO claridez_app;

ALTER TABLE public.organizations_venue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_venue FORCE ROW LEVEL SECURITY;
CREATE POLICY organizations_venue_tenant_policy
ON public.organizations_venue AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());

ALTER TABLE public.organizations_space ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_space FORCE ROW LEVEL SECURITY;
CREATE POLICY organizations_space_tenant_policy
ON public.organizations_space AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());

CREATE FUNCTION public.claridez_require_primary_venue()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_organization uuid;
    previous_context text;
    primary_count integer;
BEGIN
    target_organization := COALESCE(NEW.organization_id, OLD.organization_id);
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', target_organization::text, true
    );
    SELECT count(*) INTO primary_count FROM public.organizations_venue
    WHERE organization_id = target_organization AND is_primary AND is_active;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    IF primary_count <> 1 THEN
        RAISE EXCEPTION 'organization requires exactly one active primary venue'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_require_primary_venue() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER organizations_primary_venue_guard
AFTER INSERT OR UPDATE OR DELETE ON public.organizations_venue
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_require_primary_venue();

CREATE FUNCTION public.claridez_require_primary_space()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_organization uuid;
    previous_context text;
    primary_count integer;
BEGIN
    target_organization := COALESCE(NEW.organization_id, OLD.organization_id);
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', target_organization::text, true
    );
    SELECT count(*) INTO primary_count FROM public.organizations_space
    WHERE organization_id = target_organization AND is_primary AND is_active;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    IF primary_count <> 1 THEN
        RAISE EXCEPTION 'organization requires exactly one active primary space'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_require_primary_space() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER organizations_primary_space_guard
AFTER INSERT OR UPDATE OR DELETE ON public.organizations_space
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_require_primary_space();
"""

TENANT_SECURITY_REVERSE = r"""
DROP TRIGGER IF EXISTS organizations_primary_space_guard ON public.organizations_space;
DROP FUNCTION IF EXISTS public.claridez_require_primary_space();
DROP TRIGGER IF EXISTS organizations_primary_venue_guard ON public.organizations_venue;
DROP FUNCTION IF EXISTS public.claridez_require_primary_venue();
DROP POLICY IF EXISTS organizations_space_tenant_policy ON public.organizations_space;
ALTER TABLE public.organizations_space NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_space DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS organizations_venue_tenant_policy ON public.organizations_venue;
ALTER TABLE public.organizations_venue NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_venue DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.organizations_space FROM claridez_app;
REVOKE ALL ON TABLE public.organizations_venue FROM claridez_app;
ALTER TABLE public.organizations_space
    DROP CONSTRAINT IF EXISTS organizations_space_tenant_venue_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_membership_organizations_membership_org_id_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="Venue",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=150)),
                ("location_reference", models.CharField(blank=True, max_length=300)),
                ("is_primary", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="venues",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="Space",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=150)),
                ("is_primary", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="spaces",
                        to="organizations.organization",
                    ),
                ),
                (
                    "venue",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="spaces",
                        to="organizations.venue",
                    ),
                ),
            ],
            options={"ordering": ["venue__name", "name", "id"]},
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="organizations_venue_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"), name="organizations_venue_org_name_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_primary", True)),
                fields=("organization",),
                name="organizations_venue_one_primary_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("name", django.db.models.functions.text.Trim("name")),
                    models.Q(("name", ""), _negated=True),
                ),
                name="organizations_venue_name_canonical",
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("location_reference", ""),
                    (
                        "location_reference",
                        django.db.models.functions.text.Trim("location_reference"),
                    ),
                    _connector="OR",
                ),
                name="organizations_venue_location_canonical",
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.CheckConstraint(
                condition=models.Q(("is_primary", False), ("is_active", True), _connector="OR"),
                name="organizations_venue_primary_active",
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.CheckConstraint(
                condition=models.Q(("revision__gte", 1)),
                name="organizations_venue_revision_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="space",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="organizations_space_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="space",
            constraint=models.UniqueConstraint(
                fields=("organization", "venue", "name"),
                name="organizations_space_org_venue_name_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="space",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_primary", True)),
                fields=("organization",),
                name="organizations_space_one_primary_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="space",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("name", django.db.models.functions.text.Trim("name")),
                    models.Q(("name", ""), _negated=True),
                ),
                name="organizations_space_name_canonical",
            ),
        ),
        migrations.AddConstraint(
            model_name="space",
            constraint=models.CheckConstraint(
                condition=models.Q(("is_primary", False), ("is_active", True), _connector="OR"),
                name="organizations_space_primary_active",
            ),
        ),
        migrations.AddConstraint(
            model_name="space",
            constraint=models.CheckConstraint(
                condition=models.Q(("revision__gte", 1)),
                name="organizations_space_revision_positive",
            ),
        ),
        migrations.RunPython(create_primary_venues_and_spaces, migrations.RunPython.noop),
        migrations.RunSQL(TENANT_SECURITY_FORWARD, TENANT_SECURITY_REVERSE),
    ]
