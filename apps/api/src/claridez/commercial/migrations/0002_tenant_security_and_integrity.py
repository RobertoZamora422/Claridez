# ruff: noqa: E501

from django.db import migrations

TABLES = (
    "commercial_person",
    "commercial_personrevision",
    "commercial_eventrequest",
    "commercial_quotationsequence",
    "commercial_quotation",
    "commercial_quotationversion",
    "commercial_quotationline",
    "commercial_reservation",
)


TENANT_RELATIONS_FORWARD = """
ALTER TABLE commercial_personrevision
    ADD CONSTRAINT commercial_personrevision_tenant_person_fk
    FOREIGN KEY (organization_id, person_id)
    REFERENCES commercial_person (organization_id, id);
ALTER TABLE commercial_eventrequest
    ADD CONSTRAINT commercial_eventrequest_tenant_person_fk
    FOREIGN KEY (organization_id, person_id)
    REFERENCES commercial_person (organization_id, id);
ALTER TABLE commercial_eventrequest
    ADD CONSTRAINT commercial_eventrequest_tenant_responsible_fk
    FOREIGN KEY (organization_id, responsible_membership_id)
    REFERENCES organizations_membership (organization_id, id);
ALTER TABLE commercial_quotation
    ADD CONSTRAINT commercial_quotation_tenant_request_fk
    FOREIGN KEY (organization_id, event_request_id)
    REFERENCES commercial_eventrequest (organization_id, id);
ALTER TABLE commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_tenant_quote_fk
    FOREIGN KEY (organization_id, quotation_id)
    REFERENCES commercial_quotation (organization_id, id);
ALTER TABLE commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_tenant_issued_by_fk
    FOREIGN KEY (organization_id, issued_by_membership_id)
    REFERENCES organizations_membership (organization_id, id);
ALTER TABLE commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_tenant_accepted_by_fk
    FOREIGN KEY (organization_id, accepted_by_membership_id)
    REFERENCES organizations_membership (organization_id, id);
ALTER TABLE commercial_quotationline
    ADD CONSTRAINT commercial_quoteline_tenant_version_fk
    FOREIGN KEY (organization_id, quotation_version_id)
    REFERENCES commercial_quotationversion (organization_id, id);
ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_tenant_request_fk
    FOREIGN KEY (organization_id, event_request_id)
    REFERENCES commercial_eventrequest (organization_id, id);
ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_tenant_version_fk
    FOREIGN KEY (organization_id, quotation_version_id)
    REFERENCES commercial_quotationversion (organization_id, id);
ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_tenant_confirmed_by_fk
    FOREIGN KEY (organization_id, confirmed_by_membership_id)
    REFERENCES organizations_membership (organization_id, id);
ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_tenant_waived_by_fk
    FOREIGN KEY (organization_id, waiver_authorized_by_membership_id)
    REFERENCES organizations_membership (organization_id, id);
ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_tenant_cancelled_by_fk
    FOREIGN KEY (organization_id, cancelled_by_membership_id)
    REFERENCES organizations_membership (organization_id, id);
"""

TENANT_RELATIONS_REVERSE = """
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_tenant_cancelled_by_fk;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_tenant_waived_by_fk;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_tenant_confirmed_by_fk;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_tenant_version_fk;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_tenant_request_fk;
ALTER TABLE commercial_quotationline DROP CONSTRAINT IF EXISTS commercial_quoteline_tenant_version_fk;
ALTER TABLE commercial_quotationversion DROP CONSTRAINT IF EXISTS commercial_quoteversion_tenant_accepted_by_fk;
ALTER TABLE commercial_quotationversion DROP CONSTRAINT IF EXISTS commercial_quoteversion_tenant_issued_by_fk;
ALTER TABLE commercial_quotationversion DROP CONSTRAINT IF EXISTS commercial_quoteversion_tenant_quote_fk;
ALTER TABLE commercial_quotation DROP CONSTRAINT IF EXISTS commercial_quotation_tenant_request_fk;
ALTER TABLE commercial_eventrequest DROP CONSTRAINT IF EXISTS commercial_eventrequest_tenant_responsible_fk;
ALTER TABLE commercial_eventrequest DROP CONSTRAINT IF EXISTS commercial_eventrequest_tenant_person_fk;
ALTER TABLE commercial_personrevision DROP CONSTRAINT IF EXISTS commercial_personrevision_tenant_person_fk;
"""


INTEGRITY_FORWARD = """
ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_interval_canonical
    CHECK (
        NOT isempty(event_interval)
        AND lower(event_interval) < upper(event_interval)
        AND lower_inc(event_interval)
        AND NOT upper_inc(event_interval)
        AND NOT lower_inf(event_interval)
        AND NOT upper_inf(event_interval)
    );

ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_confirmation_evidence
    CHECK (
        (
            confirmed_at IS NULL
            AND confirmed_by_membership_id IS NULL
            AND confirmation_kind = ''
            AND recognized_deposit_amount IS NULL
            AND deposit_reported_at IS NULL
            AND deposit_reference = ''
            AND waiver_reason = ''
            AND waiver_authorized_at IS NULL
            AND waiver_authorized_by_membership_id IS NULL
        )
        OR
        (
            confirmed_at IS NOT NULL
            AND
            confirmed_by_membership_id IS NOT NULL
            AND (
                (
                    confirmation_kind = 'external_deposit'
                    AND recognized_deposit_amount > 0
                    AND deposit_reported_at IS NOT NULL
                    AND btrim(deposit_reference) <> ''
                    AND waiver_reason = ''
                    AND waiver_authorized_at IS NULL
                    AND waiver_authorized_by_membership_id IS NULL
                )
                OR
                (
                    confirmation_kind = 'waiver'
                    AND recognized_deposit_amount IS NULL
                    AND deposit_reported_at IS NULL
                    AND deposit_reference = ''
                    AND btrim(waiver_reason) <> ''
                    AND waiver_authorized_at IS NOT NULL
                    AND waiver_authorized_by_membership_id IS NOT NULL
                )
            )
        )
    );

ALTER TABLE commercial_reservation
    ADD CONSTRAINT commercial_reservation_lifecycle_evidence
    CHECK (
        (status <> 'confirmed' OR confirmed_at IS NOT NULL)
        AND (status NOT IN ('provisional', 'expired') OR confirmed_at IS NULL)
        AND (
            (
                status = 'cancelled'
                AND cancelled_at IS NOT NULL
                AND cancelled_by_membership_id IS NOT NULL
                AND btrim(cancellation_reason) <> ''
            )
            OR
            (
                status <> 'cancelled'
                AND cancelled_at IS NULL
                AND cancelled_by_membership_id IS NULL
                AND cancellation_reason = ''
            )
        )
    );

ALTER TABLE commercial_quotationversion
    ADD CONSTRAINT commercial_quoteversion_lifecycle_evidence
    CHECK (
        (
            status = 'draft'
            AND issued_at IS NULL
            AND issued_by_membership_id IS NULL
            AND accepted_at IS NULL
            AND accepted_by_membership_id IS NULL
            AND acceptance_channel = ''
            AND acceptance_note = ''
        )
        OR
        (
            status IN ('issued', 'superseded', 'withdrawn')
            AND issued_at IS NOT NULL
            AND issued_by_membership_id IS NOT NULL
            AND accepted_at IS NULL
            AND accepted_by_membership_id IS NULL
            AND acceptance_channel = ''
            AND acceptance_note = ''
        )
        OR
        (
            status = 'accepted'
            AND issued_at IS NOT NULL
            AND issued_by_membership_id IS NOT NULL
            AND accepted_at IS NOT NULL
            AND accepted_by_membership_id IS NOT NULL
            AND acceptance_channel IN ('whatsapp', 'phone_call', 'email', 'in_person', 'other')
        )
    );

CREATE FUNCTION public.claridez_guard_event_request_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;
    IF NOT (
        (OLD.status = 'new' AND NEW.status IN ('quoted', 'closed_lost'))
        OR (OLD.status = 'quoted' AND NEW.status IN ('accepted', 'closed_lost'))
        OR (OLD.status = 'accepted' AND NEW.status IN ('quoted', 'confirmed', 'closed_lost'))
        OR (OLD.status = 'confirmed' AND NEW.status = 'cancelled')
    ) THEN
        RAISE EXCEPTION 'invalid event request transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_guard_event_request_transition() FROM PUBLIC;

CREATE TRIGGER commercial_eventrequest_transition
BEFORE UPDATE OF status ON commercial_eventrequest
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_event_request_transition();

CREATE FUNCTION public.claridez_guard_reservation_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF OLD.status IN ('expired', 'cancelled')
       AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'terminal reservations are immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'provisional' AND NEW.status IN ('confirmed', 'expired', 'cancelled'))
        OR (OLD.status = 'confirmed' AND NEW.status = 'cancelled')
    ) THEN
        RAISE EXCEPTION 'invalid reservation transition' USING ERRCODE = '23514';
    END IF;
    IF OLD.confirmed_at IS NOT NULL AND ROW(
        NEW.confirmation_kind, NEW.recognized_deposit_amount,
        NEW.deposit_reported_at, NEW.deposit_reference, NEW.confirmed_at,
        NEW.confirmed_by_membership_id, NEW.waiver_reason,
        NEW.waiver_authorized_at, NEW.waiver_authorized_by_membership_id
    ) IS DISTINCT FROM ROW(
        OLD.confirmation_kind, OLD.recognized_deposit_amount,
        OLD.deposit_reported_at, OLD.deposit_reference, OLD.confirmed_at,
        OLD.confirmed_by_membership_id, OLD.waiver_reason,
        OLD.waiver_authorized_at, OLD.waiver_authorized_by_membership_id
    ) THEN
        RAISE EXCEPTION 'reservation confirmation evidence is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_guard_reservation_transition() FROM PUBLIC;

CREATE TRIGGER commercial_reservation_transition
BEFORE UPDATE ON commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_reservation_transition();

CREATE FUNCTION public.claridez_guard_person_revision()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'person revisions are immutable' USING ERRCODE = '23514';
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_guard_person_revision() FROM PUBLIC;

CREATE TRIGGER commercial_personrevision_immutable
BEFORE UPDATE OR DELETE ON commercial_personrevision
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_person_revision();

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
            NEW.event_type_snapshot, NEW.event_starts_at_snapshot,
            NEW.event_ends_at_snapshot, NEW.event_timezone_snapshot,
            NEW.estimated_guests_snapshot, NEW.general_need_snapshot,
            NEW.request_notes_snapshot, NEW.notes, NEW.subtotal,
            NEW.discount_total, NEW.total, NEW.issued_at,
            NEW.issued_by_membership_id, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.organization_id, OLD.quotation_id, OLD.version,
            OLD.request_revision, OLD.revision, OLD.valid_until, OLD.currency,
            OLD.organization_name_snapshot, OLD.person_name_snapshot,
            OLD.person_phone_snapshot, OLD.person_email_snapshot,
            OLD.event_type_snapshot, OLD.event_starts_at_snapshot,
            OLD.event_ends_at_snapshot, OLD.event_timezone_snapshot,
            OLD.estimated_guests_snapshot, OLD.general_need_snapshot,
            OLD.request_notes_snapshot, OLD.notes, OLD.subtotal,
            OLD.discount_total, OLD.total, OLD.issued_at,
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
BEFORE UPDATE OR DELETE ON commercial_quotationversion
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_quotation_version();

CREATE FUNCTION public.claridez_guard_quotation_line()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    old_status text;
    new_status text;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO old_status
        FROM public.commercial_quotationversion
        WHERE id = OLD.quotation_version_id AND organization_id = OLD.organization_id;
        IF old_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'issued quotation lines are immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO new_status
        FROM public.commercial_quotationversion
        WHERE id = NEW.quotation_version_id AND organization_id = NEW.organization_id;
        IF new_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'quotation lines require a draft version' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_guard_quotation_line() FROM PUBLIC;

CREATE TRIGGER commercial_quoteline_immutable
BEFORE INSERT OR UPDATE OR DELETE ON commercial_quotationline
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_quotation_line();

CREATE FUNCTION public.claridez_validate_quotation_totals()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    calculated_subtotal numeric(18,2);
    calculated_discount numeric(18,2);
    calculated_total numeric(18,2);
BEGIN
    IF NEW.status = 'draft' THEN
        RETURN NEW;
    END IF;
    SELECT
        COALESCE(sum(line_subtotal), 0.00),
        COALESCE(sum(discount_amount), 0.00),
        COALESCE(sum(line_total), 0.00)
    INTO calculated_subtotal, calculated_discount, calculated_total
    FROM public.commercial_quotationline
    WHERE organization_id = NEW.organization_id
      AND quotation_version_id = NEW.id;
    IF calculated_subtotal <> NEW.subtotal
       OR calculated_discount <> NEW.discount_total
       OR calculated_total <> NEW.total THEN
        RAISE EXCEPTION 'quotation aggregates do not match lines' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_validate_quotation_totals() FROM PUBLIC;

CREATE TRIGGER commercial_quoteversion_totals
AFTER INSERT OR UPDATE OF status, subtotal, discount_total, total
ON commercial_quotationversion
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_quotation_totals();

CREATE FUNCTION public.claridez_validate_reservation_confirmation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    quotation_total numeric(18,2);
BEGIN
    IF NEW.confirmed_at IS NOT NULL AND NEW.confirmation_kind = 'external_deposit' THEN
        SELECT total INTO quotation_total
        FROM public.commercial_quotationversion
        WHERE id = NEW.quotation_version_id AND organization_id = NEW.organization_id;
        IF quotation_total IS NULL OR NEW.recognized_deposit_amount > quotation_total THEN
            RAISE EXCEPTION 'recognized deposit exceeds quotation total' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION public.claridez_validate_reservation_confirmation() FROM PUBLIC;

CREATE TRIGGER commercial_reservation_confirmation
BEFORE INSERT OR UPDATE ON commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_reservation_confirmation();
"""

INTEGRITY_REVERSE = """
DROP TRIGGER IF EXISTS commercial_reservation_confirmation ON commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_validate_reservation_confirmation();
DROP TRIGGER IF EXISTS commercial_quoteversion_totals ON commercial_quotationversion;
DROP FUNCTION IF EXISTS public.claridez_validate_quotation_totals();
DROP TRIGGER IF EXISTS commercial_quoteline_immutable ON commercial_quotationline;
DROP FUNCTION IF EXISTS public.claridez_guard_quotation_line();
DROP TRIGGER IF EXISTS commercial_quoteversion_immutable ON commercial_quotationversion;
DROP FUNCTION IF EXISTS public.claridez_guard_quotation_version();
DROP TRIGGER IF EXISTS commercial_personrevision_immutable ON commercial_personrevision;
DROP FUNCTION IF EXISTS public.claridez_guard_person_revision();
DROP TRIGGER IF EXISTS commercial_reservation_transition ON commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_guard_reservation_transition();
DROP TRIGGER IF EXISTS commercial_eventrequest_transition ON commercial_eventrequest;
DROP FUNCTION IF EXISTS public.claridez_guard_event_request_transition();
ALTER TABLE commercial_quotationversion DROP CONSTRAINT IF EXISTS commercial_quoteversion_lifecycle_evidence;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_lifecycle_evidence;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_confirmation_evidence;
ALTER TABLE commercial_reservation DROP CONSTRAINT IF EXISTS commercial_reservation_interval_canonical;
"""


def _rls_forward() -> str:
    statements: list[str] = []
    for table in TABLES:
        policy = f"{table}_tenant_policy"
        delete = ", DELETE" if table == "commercial_quotationline" else ""
        statements.extend(
            [
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC;",
                f"GRANT SELECT, INSERT, UPDATE{delete} ON TABLE public.{table} TO claridez_app;",
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                (
                    f"CREATE POLICY {policy} ON public.{table} AS PERMISSIVE FOR ALL "
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
        policy = f"{table}_tenant_policy"
        statements.extend(
            [
                f"DROP POLICY IF EXISTS {policy} ON public.{table};",
                f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;",
                f"REVOKE ALL ON TABLE public.{table} FROM claridez_app;",
            ]
        )
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("commercial", "0001_initial")]

    operations = [
        migrations.RunSQL(TENANT_RELATIONS_FORWARD, TENANT_RELATIONS_REVERSE),
        migrations.RunSQL(INTEGRITY_FORWARD, INTEGRITY_REVERSE),
        migrations.RunSQL(_rls_forward(), _rls_reverse()),
    ]
