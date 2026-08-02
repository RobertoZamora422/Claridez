import uuid

import django.contrib.postgres.constraints
import django.db.models.deletion
from django.db import migrations, models

PREPARE_BACKFILL = r"""
LOCK TABLE public.commercial_reservation IN SHARE ROW EXCLUSIVE MODE;
DROP TRIGGER IF EXISTS commercial_quoteversion_immutable
    ON public.commercial_quotationversion;
DROP FUNCTION IF EXISTS public.claridez_guard_quotation_version();
DROP TRIGGER IF EXISTS commercial_reservation_transition
    ON public.commercial_reservation;
"""


def backfill_multi_space(apps, schema_editor):  # type: ignore[no-untyped-def]
    organization_model = apps.get_model("organizations", "Organization")
    membership_model = apps.get_model("organizations", "Membership")
    venue_model = apps.get_model("organizations", "Venue")
    space_model = apps.get_model("organizations", "Space")
    event_type_model = apps.get_model("catalog", "EventType")
    event_type_revision_model = apps.get_model("catalog", "EventTypeRevision")
    request_model = apps.get_model("commercial", "EventRequest")
    quotation_model = apps.get_model("commercial", "Quotation")
    version_model = apps.get_model("commercial", "QuotationVersion")
    reservation_model = apps.get_model("commercial", "Reservation")

    connection = schema_editor.connection
    organization_ids = organization_model.objects.order_by("id").values_list("id", flat=True)
    for organization_id in organization_ids:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config('claridez.organization_id', %s, true)",
                (str(organization_id),),
            )
        venue = venue_model.objects.get(organization_id=organization_id, is_primary=True)
        space = space_model.objects.get(organization_id=organization_id, is_primary=True)
        if space.venue_id != venue.id:
            raise RuntimeError("El espacio principal no pertenece a la sede principal.")

        event_types: dict[str, uuid.UUID] = {}
        requests = list(
            request_model.objects.filter(organization_id=organization_id).order_by("id")
        )
        fallback_membership_id = (
            membership_model.objects.filter(organization_id=organization_id)
            .order_by("joined_at", "id")
            .values_list("id", flat=True)
            .first()
        )
        for request in requests:
            event_type_id = event_types.get(request.event_type)
            if event_type_id is None:
                existing_event_type = event_type_model.objects.filter(
                    organization_id=organization_id, name=request.event_type
                ).first()
                event_type_id = (
                    existing_event_type.id
                    if existing_event_type is not None
                    else uuid.uuid5(organization_id, f"claridez:event-type:{request.event_type}")
                )
                if existing_event_type is None:
                    actor_membership_id = (
                        request.responsible_membership_id or fallback_membership_id
                    )
                    if actor_membership_id is None:
                        raise RuntimeError(
                            "Un histórico comercial carece de membresía responsable."
                        )
                    event_type_model.objects.create(
                        id=event_type_id,
                        organization_id=organization_id,
                        name=request.event_type,
                        is_active=True,
                        revision=1,
                    )
                    event_type_revision_model.objects.create(
                        id=uuid.uuid5(event_type_id, "claridez:event-type-revision:1"),
                        organization_id=organization_id,
                        event_type_id=event_type_id,
                        revision=1,
                        name=request.event_type,
                        is_active=True,
                        changed_by_membership_id=actor_membership_id,
                    )
                event_types[request.event_type] = event_type_id
            request_model.objects.filter(pk=request.pk).update(
                event_type_definition_id=event_type_id,
                space_id=space.id,
            )

        quotations = {
            row.id: row.event_request_id
            for row in quotation_model.objects.filter(organization_id=organization_id)
        }
        requests_by_id = {
            row.id: row for row in request_model.objects.filter(organization_id=organization_id)
        }
        for version in version_model.objects.filter(organization_id=organization_id):
            request_id = quotations[version.quotation_id]
            event_request = requests_by_id[request_id]
            version_model.objects.filter(pk=version.pk).update(
                event_type_definition_snapshot_id=event_request.event_type_definition_id,
                venue_snapshot_id=venue.id,
                venue_name_snapshot=venue.name,
                space_snapshot_id=space.id,
                space_name_snapshot=space.name,
            )
        for reservation in reservation_model.objects.filter(organization_id=organization_id):
            version = version_model.objects.get(pk=reservation.quotation_version_id)
            reservation_model.objects.filter(pk=reservation.pk).update(
                space_id=version.space_snapshot_id
            )

        if request_model.objects.filter(
            organization_id=organization_id,
            event_type_definition_id__isnull=True,
        ).exists():
            raise RuntimeError("El backfill dejó solicitudes sin tipo de evento.")
        if version_model.objects.filter(
            organization_id=organization_id, space_snapshot_id__isnull=True
        ).exists():
            raise RuntimeError("El backfill dejó cotizaciones sin espacio.")
        if reservation_model.objects.filter(
            organization_id=organization_id, space_id__isnull=True
        ).exists():
            raise RuntimeError("El backfill dejó reservas sin espacio.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.set_config('claridez.organization_id', '', true)")


TENANT_RELATIONS_FORWARD = r"""
ALTER TABLE public.commercial_eventrequest
    ADD CONSTRAINT commercial_eventrequest_tenant_eventtype_fk
    FOREIGN KEY (organization_id, event_type_definition_id)
    REFERENCES public.catalog_eventtype (organization_id, id);
ALTER TABLE public.commercial_eventrequest
    ADD CONSTRAINT commercial_eventrequest_tenant_space_fk
    FOREIGN KEY (organization_id, space_id)
    REFERENCES public.organizations_space (organization_id, id);
ALTER TABLE public.commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_tenant_eventtype_fk
    FOREIGN KEY (organization_id, event_type_definition_snapshot_id)
    REFERENCES public.catalog_eventtype (organization_id, id);
ALTER TABLE public.commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_tenant_venue_fk
    FOREIGN KEY (organization_id, venue_snapshot_id)
    REFERENCES public.organizations_venue (organization_id, id);
ALTER TABLE public.commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_tenant_space_fk
    FOREIGN KEY (organization_id, space_snapshot_id)
    REFERENCES public.organizations_space (organization_id, id);
ALTER TABLE public.commercial_quotationline
    ADD CONSTRAINT commercial_quoteline_tenant_catalog_revision_fk
    FOREIGN KEY (organization_id, catalog_item_revision_id)
    REFERENCES public.catalog_catalogitemrevision (organization_id, id);
ALTER TABLE public.commercial_quotationline
    ADD CONSTRAINT commercial_quoteline_tenant_catalog_price_fk
    FOREIGN KEY (organization_id, catalog_price_id)
    REFERENCES public.catalog_catalogprice (organization_id, id);
ALTER TABLE public.commercial_reservation
    ADD CONSTRAINT commercial_reservation_tenant_space_fk
    FOREIGN KEY (organization_id, space_id)
    REFERENCES public.organizations_space (organization_id, id);
"""

TENANT_RELATIONS_REVERSE = r"""
ALTER TABLE public.commercial_reservation
    DROP CONSTRAINT IF EXISTS commercial_reservation_tenant_space_fk;
ALTER TABLE public.commercial_quotationline
    DROP CONSTRAINT IF EXISTS commercial_quoteline_tenant_catalog_price_fk;
ALTER TABLE public.commercial_quotationline
    DROP CONSTRAINT IF EXISTS commercial_quoteline_tenant_catalog_revision_fk;
ALTER TABLE public.commercial_quotationversion
    DROP CONSTRAINT IF EXISTS commercial_quoteversion_tenant_space_fk;
ALTER TABLE public.commercial_quotationversion
    DROP CONSTRAINT IF EXISTS commercial_quoteversion_tenant_venue_fk;
ALTER TABLE public.commercial_quotationversion
    DROP CONSTRAINT IF EXISTS commercial_quoteversion_tenant_eventtype_fk;
ALTER TABLE public.commercial_eventrequest
    DROP CONSTRAINT IF EXISTS commercial_eventrequest_tenant_space_fk;
ALTER TABLE public.commercial_eventrequest
    DROP CONSTRAINT IF EXISTS commercial_eventrequest_tenant_eventtype_fk;
"""

RESTORE_GUARDS_FORWARD = r"""
CREATE FUNCTION public.claridez_guard_quotation_version()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'issued quotation versions are immutable' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status IN ('accepted', 'superseded', 'withdrawn') THEN
        IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'terminal quotation versions are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'issued' THEN
        IF ROW(
            NEW.id, NEW.organization_id, NEW.quotation_id, NEW.version,
            NEW.request_revision, NEW.revision, NEW.valid_until, NEW.currency,
            NEW.organization_name_snapshot, NEW.person_name_snapshot,
            NEW.person_phone_snapshot, NEW.person_email_snapshot,
            NEW.event_type_definition_snapshot_id, NEW.event_type_snapshot,
            NEW.venue_snapshot_id, NEW.venue_name_snapshot,
            NEW.space_snapshot_id, NEW.space_name_snapshot,
            NEW.event_starts_at_snapshot, NEW.event_ends_at_snapshot,
            NEW.event_timezone_snapshot, NEW.estimated_guests_snapshot,
            NEW.general_need_snapshot, NEW.request_notes_snapshot, NEW.notes,
            NEW.subtotal, NEW.discount_total, NEW.total, NEW.issued_at,
            NEW.issued_by_membership_id, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.organization_id, OLD.quotation_id, OLD.version,
            OLD.request_revision, OLD.revision, OLD.valid_until, OLD.currency,
            OLD.organization_name_snapshot, OLD.person_name_snapshot,
            OLD.person_phone_snapshot, OLD.person_email_snapshot,
            OLD.event_type_definition_snapshot_id, OLD.event_type_snapshot,
            OLD.venue_snapshot_id, OLD.venue_name_snapshot,
            OLD.space_snapshot_id, OLD.space_name_snapshot,
            OLD.event_starts_at_snapshot, OLD.event_ends_at_snapshot,
            OLD.event_timezone_snapshot, OLD.estimated_guests_snapshot,
            OLD.general_need_snapshot, OLD.request_notes_snapshot, OLD.notes,
            OLD.subtotal, OLD.discount_total, OLD.total, OLD.issued_at,
            OLD.issued_by_membership_id, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'issued quotation snapshots are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.status NOT IN ('issued', 'accepted', 'superseded', 'withdrawn') THEN
            RAISE EXCEPTION 'invalid quotation transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_quotation_version() FROM PUBLIC;
CREATE TRIGGER commercial_quoteversion_immutable
BEFORE UPDATE OR DELETE ON public.commercial_quotationversion
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_quotation_version();

CREATE TRIGGER commercial_reservation_transition
BEFORE UPDATE ON public.commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_reservation_transition();

CREATE FUNCTION public.claridez_validate_quote_space()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    expected_venue uuid;
BEGIN
    SELECT venue_id INTO expected_venue
    FROM public.organizations_space
    WHERE organization_id = NEW.organization_id AND id = NEW.space_snapshot_id;
    IF expected_venue IS DISTINCT FROM NEW.venue_snapshot_id THEN
        RAISE EXCEPTION 'quotation venue and space are incoherent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_quote_space() FROM PUBLIC;
CREATE TRIGGER commercial_quoteversion_space_coherence
BEFORE INSERT OR UPDATE ON public.commercial_quotationversion
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_quote_space();

CREATE FUNCTION public.claridez_validate_catalog_line()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    revision_item uuid;
    revision_name text;
    revision_unit text;
    revision_components jsonb;
    price_item uuid;
    price_amount numeric;
BEGIN
    IF NEW.source = 'ad_hoc' THEN
        RETURN NEW;
    END IF;
    SELECT item_id, name, unit_label, package_components
    INTO revision_item, revision_name, revision_unit, revision_components
    FROM public.catalog_catalogitemrevision
    WHERE organization_id = NEW.organization_id AND id = NEW.catalog_item_revision_id;
    SELECT item_id, amount INTO price_item, price_amount FROM public.catalog_catalogprice
    WHERE organization_id = NEW.organization_id AND id = NEW.catalog_price_id;
    IF revision_item IS NULL OR revision_item IS DISTINCT FROM price_item
       OR NEW.description IS DISTINCT FROM revision_name
       OR NEW.unit_label IS DISTINCT FROM revision_unit
       OR NEW.unit_price IS DISTINCT FROM price_amount
       OR NEW.package_components_snapshot IS DISTINCT FROM revision_components THEN
        RAISE EXCEPTION 'catalog quotation line is incoherent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_catalog_line() FROM PUBLIC;
CREATE TRIGGER commercial_quoteline_catalog_coherence
BEFORE INSERT OR UPDATE ON public.commercial_quotationline
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_catalog_line();

DROP TRIGGER IF EXISTS commercial_reservation_coherence ON public.commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_validate_reservation_coherence();
CREATE FUNCTION public.claridez_validate_reservation_coherence()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    expected_request_id uuid;
    expected_space_id uuid;
    expected_interval tstzrange;
    expected_timezone text;
    quotation_status text;
BEGIN
    SELECT quotation.event_request_id, version.space_snapshot_id,
           tstzrange(version.event_starts_at_snapshot, version.event_ends_at_snapshot, '[)'),
           version.event_timezone_snapshot, version.status
    INTO expected_request_id, expected_space_id, expected_interval,
         expected_timezone, quotation_status
    FROM public.commercial_quotationversion AS version
    JOIN public.commercial_quotation AS quotation
      ON quotation.organization_id = version.organization_id
     AND quotation.id = version.quotation_id
    WHERE version.organization_id = NEW.organization_id
      AND version.id = NEW.quotation_version_id;
    IF NOT FOUND OR quotation_status IS DISTINCT FROM 'accepted' THEN
        RAISE EXCEPTION 'reservation requires an accepted quotation version'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.event_request_id IS DISTINCT FROM expected_request_id
       OR NEW.space_id IS DISTINCT FROM expected_space_id
       OR NEW.event_interval IS DISTINCT FROM expected_interval
       OR NEW.event_timezone IS DISTINCT FROM expected_timezone THEN
        RAISE EXCEPTION 'reservation does not match quotation snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_reservation_coherence() FROM PUBLIC;
CREATE TRIGGER commercial_reservation_coherence
BEFORE INSERT OR UPDATE ON public.commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_reservation_coherence();
"""

RESTORE_GUARDS_REVERSE = r"""
DROP TRIGGER IF EXISTS commercial_quoteline_catalog_coherence
    ON public.commercial_quotationline;
DROP FUNCTION IF EXISTS public.claridez_validate_catalog_line();
DROP TRIGGER IF EXISTS commercial_quoteversion_space_coherence
    ON public.commercial_quotationversion;
DROP FUNCTION IF EXISTS public.claridez_validate_quote_space();
DROP TRIGGER IF EXISTS commercial_reservation_coherence ON public.commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_validate_reservation_coherence();
CREATE FUNCTION public.claridez_validate_reservation_coherence()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    expected_request_id uuid;
    expected_interval tstzrange;
    expected_timezone text;
    quotation_status text;
BEGIN
    SELECT quotation.event_request_id,
           tstzrange(version.event_starts_at_snapshot, version.event_ends_at_snapshot, '[)'),
           version.event_timezone_snapshot, version.status
    INTO expected_request_id, expected_interval, expected_timezone, quotation_status
    FROM public.commercial_quotationversion AS version
    JOIN public.commercial_quotation AS quotation
      ON quotation.organization_id = version.organization_id
     AND quotation.id = version.quotation_id
    WHERE version.organization_id = NEW.organization_id
      AND version.id = NEW.quotation_version_id;
    IF NOT FOUND OR quotation_status IS DISTINCT FROM 'accepted' THEN
        RAISE EXCEPTION 'reservation requires an accepted quotation version'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.event_request_id IS DISTINCT FROM expected_request_id
       OR NEW.event_interval IS DISTINCT FROM expected_interval
       OR NEW.event_timezone IS DISTINCT FROM expected_timezone THEN
        RAISE EXCEPTION 'reservation does not match quotation snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_reservation_coherence() FROM PUBLIC;
CREATE TRIGGER commercial_reservation_coherence
BEFORE INSERT OR UPDATE ON public.commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_reservation_coherence();

DROP TRIGGER IF EXISTS commercial_quoteversion_immutable
    ON public.commercial_quotationversion;
DROP FUNCTION IF EXISTS public.claridez_guard_quotation_version();
CREATE FUNCTION public.claridez_guard_quotation_version()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'issued quotation versions are immutable' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status IN ('accepted', 'superseded', 'withdrawn') THEN
        IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'terminal quotation versions are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'issued' THEN
        IF (
            to_jsonb(NEW) - ARRAY[
                'status', 'accepted_at', 'accepted_by_membership_id',
                'acceptance_channel', 'acceptance_note', 'updated_at'
            ]
        ) IS DISTINCT FROM (
            to_jsonb(OLD) - ARRAY[
                'status', 'accepted_at', 'accepted_by_membership_id',
                'acceptance_channel', 'acceptance_note', 'updated_at'
            ]
        ) THEN
            RAISE EXCEPTION 'issued quotation snapshots are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.status NOT IN ('issued', 'accepted', 'superseded', 'withdrawn') THEN
            RAISE EXCEPTION 'invalid quotation transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_quotation_version() FROM PUBLIC;
CREATE TRIGGER commercial_quoteversion_immutable
BEFORE UPDATE OR DELETE ON public.commercial_quotationversion
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_quotation_version();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
        ("commercial", "0003_hardening_5_1_1"),
        ("operations", "0002_commercial_operations_guardian"),
        ("organizations", "0004_venues_and_spaces"),
    ]
    operations = [
        migrations.AddField(
            model_name="eventrequest",
            name="event_type_definition",
            field=models.ForeignKey(
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="event_requests",
                to="catalog.eventtype",
            ),
        ),
        migrations.AddField(
            model_name="eventrequest",
            name="space",
            field=models.ForeignKey(
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="event_requests",
                to="organizations.space",
            ),
        ),
        migrations.AddField(
            model_name="quotationline",
            name="catalog_item_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_lines",
                to="catalog.catalogitemrevision",
            ),
        ),
        migrations.AddField(
            model_name="quotationline",
            name="catalog_price",
            field=models.ForeignKey(
                blank=True,
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_lines",
                to="catalog.catalogprice",
            ),
        ),
        migrations.AddField(
            model_name="quotationline",
            name="package_components_snapshot",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="quotationline",
            name="source",
            field=models.CharField(
                choices=[("ad_hoc", "Línea ad hoc"), ("catalog", "Catálogo")],
                default="ad_hoc",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="quotationversion",
            name="event_type_definition_snapshot",
            field=models.ForeignKey(
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_snapshots",
                to="catalog.eventtype",
            ),
        ),
        migrations.AddField(
            model_name="quotationversion",
            name="venue_name_snapshot",
            field=models.CharField(null=True, max_length=150),
        ),
        migrations.AddField(
            model_name="quotationversion",
            name="venue_snapshot",
            field=models.ForeignKey(
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_snapshots",
                to="organizations.venue",
            ),
        ),
        migrations.AddField(
            model_name="quotationversion",
            name="space_name_snapshot",
            field=models.CharField(null=True, max_length=150),
        ),
        migrations.AddField(
            model_name="quotationversion",
            name="space_snapshot",
            field=models.ForeignKey(
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_snapshots",
                to="organizations.space",
            ),
        ),
        migrations.AddField(
            model_name="reservation",
            name="space",
            field=models.ForeignKey(
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reservations",
                to="organizations.space",
            ),
        ),
        migrations.RunSQL(PREPARE_BACKFILL, migrations.RunSQL.noop),
        migrations.RunPython(backfill_multi_space, migrations.RunPython.noop),
        migrations.RunSQL("SET CONSTRAINTS ALL IMMEDIATE;", migrations.RunSQL.noop),
        migrations.RemoveConstraint(
            model_name="reservation", name="commercial_reservation_no_overlap"
        ),
        migrations.AlterField(
            model_name="eventrequest",
            name="event_type_definition",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="event_requests",
                to="catalog.eventtype",
            ),
        ),
        migrations.AlterField(
            model_name="eventrequest",
            name="space",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="event_requests",
                to="organizations.space",
            ),
        ),
        migrations.AlterField(
            model_name="quotationversion",
            name="event_type_definition_snapshot",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_snapshots",
                to="catalog.eventtype",
            ),
        ),
        migrations.AlterField(
            model_name="quotationversion",
            name="venue_name_snapshot",
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name="quotationversion",
            name="venue_snapshot",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_snapshots",
                to="organizations.venue",
            ),
        ),
        migrations.AlterField(
            model_name="quotationversion",
            name="space_name_snapshot",
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name="quotationversion",
            name="space_snapshot",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_snapshots",
                to="organizations.space",
            ),
        ),
        migrations.AlterField(
            model_name="reservation",
            name="space",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reservations",
                to="organizations.space",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotationline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("catalog_item_revision__isnull", True),
                        ("catalog_price__isnull", True),
                        ("package_components_snapshot", []),
                        ("source", "ad_hoc"),
                    ),
                    models.Q(
                        ("catalog_item_revision__isnull", False),
                        ("catalog_price__isnull", False),
                        ("source", "catalog"),
                    ),
                    _connector="OR",
                ),
                name="commercial_quoteline_source_coherent",
            ),
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("status__in", ["provisional", "confirmed"])),
                expressions=[("organization", "="), ("space", "="), ("event_interval", "&&")],
                name="commercial_reservation_no_overlap",
            ),
        ),
        migrations.RunSQL(TENANT_RELATIONS_FORWARD, TENANT_RELATIONS_REVERSE),
        migrations.RunSQL(RESTORE_GUARDS_FORWARD, RESTORE_GUARDS_REVERSE),
    ]
