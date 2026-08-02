import uuid

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models

TABLES = (
    "catalog_eventtype",
    "catalog_eventtyperevision",
    "catalog_catalogitem",
    "catalog_catalogitemrevision",
    "catalog_packagecomponent",
    "catalog_catalogprice",
)

TENANT_INTEGRITY_FORWARD = r"""
ALTER TABLE public.catalog_eventtyperevision
    ADD CONSTRAINT catalog_eventtyperevision_tenant_type_fk
    FOREIGN KEY (organization_id, event_type_id)
    REFERENCES public.catalog_eventtype (organization_id, id);
ALTER TABLE public.catalog_eventtyperevision
    ADD CONSTRAINT catalog_eventtyperevision_tenant_actor_fk
    FOREIGN KEY (organization_id, changed_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.catalog_catalogitemrevision
    ADD CONSTRAINT catalog_itemrevision_tenant_item_fk
    FOREIGN KEY (organization_id, item_id)
    REFERENCES public.catalog_catalogitem (organization_id, id);
ALTER TABLE public.catalog_catalogitemrevision
    ADD CONSTRAINT catalog_itemrevision_tenant_actor_fk
    FOREIGN KEY (organization_id, changed_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.catalog_catalogprice
    ADD CONSTRAINT catalog_price_tenant_item_fk
    FOREIGN KEY (organization_id, item_id)
    REFERENCES public.catalog_catalogitem (organization_id, id);
ALTER TABLE public.catalog_catalogprice
    ADD CONSTRAINT catalog_price_tenant_actor_fk
    FOREIGN KEY (organization_id, created_by_membership_id)
    REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.catalog_packagecomponent
    ADD CONSTRAINT catalog_component_tenant_package_fk
    FOREIGN KEY (organization_id, package_id)
    REFERENCES public.catalog_catalogitem (organization_id, id);
ALTER TABLE public.catalog_packagecomponent
    ADD CONSTRAINT catalog_component_tenant_item_fk
    FOREIGN KEY (organization_id, component_id)
    REFERENCES public.catalog_catalogitem (organization_id, id);
ALTER TABLE public.catalog_packagecomponent
    ADD CONSTRAINT catalog_component_tenant_revision_fk
    FOREIGN KEY (organization_id, component_revision_id)
    REFERENCES public.catalog_catalogitemrevision (organization_id, id);

ALTER TABLE public.catalog_catalogprice
    ADD CONSTRAINT catalog_price_validity_canonical
    CHECK (
        NOT isempty(validity)
        AND lower_inc(validity)
        AND NOT upper_inc(validity)
        AND NOT lower_inf(validity)
        AND (upper_inf(validity) OR lower(validity) < upper(validity))
    );

CREATE FUNCTION public.claridez_guard_catalog_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'catalog history is immutable' USING ERRCODE = '23514';
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_catalog_history() FROM PUBLIC;
CREATE TRIGGER catalog_eventtyperevision_immutable
BEFORE UPDATE OR DELETE ON public.catalog_eventtyperevision
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_catalog_history();
CREATE TRIGGER catalog_itemrevision_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogitemrevision
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_catalog_history();
CREATE TRIGGER catalog_component_immutable
BEFORE UPDATE OR DELETE ON public.catalog_packagecomponent
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_catalog_history();

CREATE FUNCTION public.claridez_guard_catalog_price()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'catalog prices cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(
        NEW.id, NEW.organization_id, NEW.item_id, NEW.amount, NEW.currency,
        NEW.revision, NEW.created_by_membership_id, NEW.created_at,
        lower(NEW.validity), lower_inc(NEW.validity), upper_inc(NEW.validity)
    ) IS DISTINCT FROM ROW(
        OLD.id, OLD.organization_id, OLD.item_id, OLD.amount, OLD.currency,
        OLD.revision, OLD.created_by_membership_id, OLD.created_at,
        lower(OLD.validity), lower_inc(OLD.validity), upper_inc(OLD.validity)
    ) OR upper(NEW.validity) IS NULL
      OR upper(NEW.validity) >= upper(OLD.validity) THEN
        RAISE EXCEPTION 'catalog price history is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_catalog_price() FROM PUBLIC;
CREATE TRIGGER catalog_price_guard
BEFORE UPDATE OR DELETE ON public.catalog_catalogprice
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_catalog_price();

CREATE FUNCTION public.claridez_validate_package_component()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    package_kind text;
    component_kind text;
    revision_item uuid;
    package_revision_exists boolean;
BEGIN
    SELECT kind INTO package_kind FROM public.catalog_catalogitem
    WHERE organization_id = NEW.organization_id AND id = NEW.package_id;
    SELECT kind INTO component_kind FROM public.catalog_catalogitem
    WHERE organization_id = NEW.organization_id AND id = NEW.component_id;
    SELECT item_id INTO revision_item FROM public.catalog_catalogitemrevision
    WHERE organization_id = NEW.organization_id AND id = NEW.component_revision_id;
    SELECT EXISTS(
        SELECT 1 FROM public.catalog_catalogitemrevision
        WHERE organization_id = NEW.organization_id
          AND item_id = NEW.package_id
          AND revision = NEW.package_revision
    ) INTO package_revision_exists;
    IF package_kind IS DISTINCT FROM 'package'
       OR component_kind NOT IN ('service', 'product')
       OR revision_item IS DISTINCT FROM NEW.component_id
       OR NOT package_revision_exists THEN
        RAISE EXCEPTION 'package component is incoherent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_package_component() FROM PUBLIC;
CREATE TRIGGER catalog_component_coherence
BEFORE INSERT ON public.catalog_packagecomponent
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_package_component();
"""

TENANT_INTEGRITY_REVERSE = r"""
DROP TRIGGER IF EXISTS catalog_component_coherence ON public.catalog_packagecomponent;
DROP FUNCTION IF EXISTS public.claridez_validate_package_component();
DROP TRIGGER IF EXISTS catalog_price_guard ON public.catalog_catalogprice;
DROP FUNCTION IF EXISTS public.claridez_guard_catalog_price();
DROP TRIGGER IF EXISTS catalog_component_immutable ON public.catalog_packagecomponent;
DROP TRIGGER IF EXISTS catalog_itemrevision_immutable ON public.catalog_catalogitemrevision;
DROP TRIGGER IF EXISTS catalog_eventtyperevision_immutable ON public.catalog_eventtyperevision;
DROP FUNCTION IF EXISTS public.claridez_guard_catalog_history();
ALTER TABLE public.catalog_catalogprice
    DROP CONSTRAINT IF EXISTS catalog_price_validity_canonical;
ALTER TABLE public.catalog_packagecomponent
    DROP CONSTRAINT IF EXISTS catalog_component_tenant_revision_fk;
ALTER TABLE public.catalog_packagecomponent
    DROP CONSTRAINT IF EXISTS catalog_component_tenant_item_fk;
ALTER TABLE public.catalog_packagecomponent
    DROP CONSTRAINT IF EXISTS catalog_component_tenant_package_fk;
ALTER TABLE public.catalog_catalogprice DROP CONSTRAINT IF EXISTS catalog_price_tenant_actor_fk;
ALTER TABLE public.catalog_catalogprice DROP CONSTRAINT IF EXISTS catalog_price_tenant_item_fk;
ALTER TABLE public.catalog_catalogitemrevision
    DROP CONSTRAINT IF EXISTS catalog_itemrevision_tenant_actor_fk;
ALTER TABLE public.catalog_catalogitemrevision
    DROP CONSTRAINT IF EXISTS catalog_itemrevision_tenant_item_fk;
ALTER TABLE public.catalog_eventtyperevision
    DROP CONSTRAINT IF EXISTS catalog_eventtyperevision_tenant_actor_fk;
ALTER TABLE public.catalog_eventtyperevision
    DROP CONSTRAINT IF EXISTS catalog_eventtyperevision_tenant_type_fk;
"""


def _rls_forward() -> str:
    statements: list[str] = []
    mutable = {"catalog_eventtype", "catalog_catalogitem", "catalog_catalogprice"}
    for table in TABLES:
        grant = "SELECT, INSERT, UPDATE" if table in mutable else "SELECT, INSERT"
        statements.extend(
            [
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC;",
                f"GRANT {grant} ON TABLE public.{table} TO claridez_app;",
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                (
                    f"CREATE POLICY {table}_tenant_policy ON public.{table} AS PERMISSIVE FOR ALL "
                    "TO claridez_app, claridez_migrator, claridez_test_runner "
                    "USING (organization_id = public.claridez_current_organization_id()) "
                    "WITH CHECK (organization_id = public.claridez_current_organization_id());"
                ),
            ]
        )
    return "\n".join(statements)


def _rls_reverse() -> str:
    statements: list[str] = []
    for table in reversed(TABLES):
        statements.extend(
            [
                f"DROP POLICY IF EXISTS {table}_tenant_policy ON public.{table};",
                f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;",
                f"REVOKE ALL ON TABLE public.{table} FROM claridez_app;",
            ]
        )
    return "\n".join(statements)


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("commercial", "0001_initial"),
        ("organizations", "0004_venues_and_spaces"),
    ]
    operations = [
        migrations.CreateModel(
            name="EventType",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("name", models.CharField(max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["name", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="catalog_eventtype_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "name"), name="catalog_eventtype_org_name_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("name", django.db.models.functions.text.Trim("name")),
                            models.Q(("name", ""), _negated=True),
                        ),
                        name="catalog_eventtype_name_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)),
                        name="catalog_eventtype_revision_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CatalogItem",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("service", "Servicio"),
                            ("product", "Producto"),
                            ("package", "Paquete"),
                        ],
                        max_length=16,
                    ),
                ),
                ("name", models.CharField(max_length=150)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("unit_label", models.CharField(max_length=40)),
                ("is_active", models.BooleanField(default=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["kind", "name", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="catalog_item_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "kind", "name"),
                        name="catalog_item_org_kind_name_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("kind__in", ["service", "product", "package"])),
                        name="catalog_item_kind_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("name", django.db.models.functions.text.Trim("name")),
                            models.Q(("name", ""), _negated=True),
                        ),
                        name="catalog_item_name_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("unit_label", django.db.models.functions.text.Trim("unit_label")),
                            models.Q(("unit_label", ""), _negated=True),
                        ),
                        name="catalog_item_unit_canonical",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)),
                        name="catalog_item_revision_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EventTypeRevision",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revision", models.PositiveIntegerField()),
                ("name", models.CharField(max_length=100)),
                ("is_active", models.BooleanField()),
                (
                    "changed_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.membership",
                    ),
                ),
                (
                    "event_type",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="catalog.eventtype",
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
            ],
            options={
                "ordering": ["event_type_id", "revision"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="catalog_eventtyperevision_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "event_type", "revision"),
                        name="catalog_eventtyperevision_org_type_rev_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)),
                        name="catalog_eventtyperevision_revision_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CatalogItemRevision",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revision", models.PositiveIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("service", "Servicio"),
                            ("product", "Producto"),
                            ("package", "Paquete"),
                        ],
                        max_length=16,
                    ),
                ),
                ("name", models.CharField(max_length=150)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("unit_label", models.CharField(max_length=40)),
                ("is_active", models.BooleanField()),
                ("package_components", models.JSONField(default=list)),
                (
                    "changed_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.membership",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="catalog.catalogitem",
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
            ],
            options={
                "ordering": ["item_id", "revision"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="catalog_itemrevision_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "item", "revision"),
                        name="catalog_itemrevision_org_item_rev_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)),
                        name="catalog_itemrevision_revision_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CatalogPrice",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("validity", django.contrib.postgres.fields.ranges.DateTimeRangeField()),
                ("revision", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by_membership",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.membership",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="prices",
                        to="catalog.catalogitem",
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
            ],
            options={
                "ordering": ["item_id", "validity", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="catalog_price_org_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gte", 0)), name="catalog_price_amount_valid"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("currency", "USD")), name="catalog_price_currency_usd"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gte", 1)),
                        name="catalog_price_revision_positive",
                    ),
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        expressions=[("organization", "="), ("item", "="), ("validity", "&&")],
                        name="catalog_price_no_overlap",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PackageComponent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("package_revision", models.PositiveIntegerField()),
                ("position", models.PositiveIntegerField()),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                (
                    "component",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="included_in_packages",
                        to="catalog.catalogitem",
                    ),
                ),
                (
                    "component_revision",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="package_component_uses",
                        to="catalog.catalogitemrevision",
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
                    "package",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="package_components",
                        to="catalog.catalogitem",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="catalog_component_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "package", "package_revision", "position"),
                        name="catalog_component_org_package_position_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "package", "package_revision", "component"),
                        name="catalog_component_org_package_item_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("package_revision__gte", 1), ("position__gte", 1), ("quantity__gt", 0)
                        ),
                        name="catalog_component_values_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("package", models.F("component")), _negated=True),
                        name="catalog_component_not_self",
                    ),
                ],
            },
        ),
        migrations.RunSQL(TENANT_INTEGRITY_FORWARD, TENANT_INTEGRITY_REVERSE),
        migrations.RunSQL(_rls_forward(), _rls_reverse()),
    ]
