from django.db import migrations

CURRENCY_TABLES = (
    ("receivables_receivableobligation", "recv_obligation_currency_ck"),
    ("receivables_collectionscheduledue", "recv_due_currency_ck"),
    ("receivables_receivedpayment", "recv_payment_currency_ck"),
    ("receivables_paymentapplication", "recv_application_currency_ck"),
    ("receivables_receivableadjustment", "recv_adjustment_currency_ck"),
    ("receivables_movementreversal", "recv_reversal_currency_ck"),
    ("receivables_refundrecord", "recv_refund_currency_ck"),
    ("receivables_refundapplication", "recv_refundapp_currency_ck"),
)


def _currency_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} ADD CONSTRAINT {name} CHECK (currency ~ '^[A-Z]{{3}}$');"
        for table, name in CURRENCY_TABLES
    )


def _currency_reverse_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name};"
        for table, name in reversed(CURRENCY_TABLES)
    )


GUARDS_SQL = r"""
ALTER TABLE public.receivables_movementreversal
ADD CONSTRAINT recv_reversal_target_kind_ck
CHECK (target_kind IN ('payment', 'application', 'adjustment', 'refund'));

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_reversal_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_row record;
    dependent_count bigint;
BEGIN
    IF NEW.target_kind = 'payment' THEN
        SELECT * INTO target_row FROM public.receivables_receivedpayment
        WHERE organization_id = NEW.organization_id AND id = NEW.target_id FOR UPDATE;
        SELECT
            (SELECT count(*) FROM public.receivables_paymentapplication application
             LEFT JOIN public.receivables_movementreversal reversal
               ON reversal.organization_id = application.organization_id
              AND reversal.target_kind = 'application' AND reversal.target_id = application.id
             WHERE application.organization_id = NEW.organization_id
               AND application.payment_id = NEW.target_id AND reversal.id IS NULL)
            +
            (SELECT count(*) FROM public.receivables_refundrecord refund
             LEFT JOIN public.receivables_movementreversal reversal
               ON reversal.organization_id = refund.organization_id
              AND reversal.target_kind = 'refund' AND reversal.target_id = refund.id
             WHERE refund.organization_id = NEW.organization_id
               AND refund.payment_id = NEW.target_id AND reversal.id IS NULL)
        INTO dependent_count;
    ELSIF NEW.target_kind = 'application' THEN
        SELECT * INTO target_row FROM public.receivables_paymentapplication
        WHERE organization_id = NEW.organization_id AND id = NEW.target_id FOR UPDATE;
        SELECT count(*) INTO dependent_count
        FROM public.receivables_refundapplication allocation
        LEFT JOIN public.receivables_movementreversal reversal
          ON reversal.organization_id = allocation.organization_id
         AND reversal.target_kind = 'refund' AND reversal.target_id = allocation.refund_id
        WHERE allocation.organization_id = NEW.organization_id
          AND allocation.payment_application_id = NEW.target_id AND reversal.id IS NULL;
    ELSIF NEW.target_kind = 'adjustment' THEN
        SELECT * INTO target_row FROM public.receivables_receivableadjustment
        WHERE organization_id = NEW.organization_id AND id = NEW.target_id FOR UPDATE;
        dependent_count := 0;
    ELSE
        SELECT * INTO target_row FROM public.receivables_refundrecord
        WHERE organization_id = NEW.organization_id AND id = NEW.target_id FOR UPDATE;
        dependent_count := 0;
    END IF;
    IF target_row.id IS NULL THEN
        RAISE EXCEPTION 'reversal target does not exist' USING ERRCODE = '23514';
    END IF;
    IF NEW.amount <> target_row.amount OR NEW.currency <> target_row.currency THEN
        RAISE EXCEPTION 'reversal must preserve exact target effect' USING ERRCODE = '23514';
    END IF;
    IF dependent_count <> 0 THEN
        RAISE EXCEPTION 'reversal target has active dependents' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_refund_allocation_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    refund_row record;
    application_row record;
    allocated_to_refund numeric(18,2);
    restored_from_application numeric(18,2);
BEGIN
    SELECT * INTO application_row FROM public.receivables_paymentapplication
    WHERE organization_id = NEW.organization_id AND id = NEW.payment_application_id
    FOR UPDATE;
    SELECT * INTO refund_row FROM public.receivables_refundrecord
    WHERE organization_id = NEW.organization_id AND id = NEW.refund_id FOR UPDATE;
    IF refund_row.id IS NULL OR application_row.id IS NULL
       OR refund_row.payment_id <> application_row.payment_id
       OR NEW.currency <> refund_row.currency OR NEW.currency <> application_row.currency
       OR (refund_row.obligation_id IS NOT NULL
           AND refund_row.obligation_id <> application_row.obligation_id) THEN
        RAISE EXCEPTION 'refund allocation context mismatch' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.receivables_movementreversal reversal
        WHERE reversal.organization_id = NEW.organization_id
          AND reversal.target_kind = 'application'
          AND reversal.target_id = application_row.id
    ) THEN
        RAISE EXCEPTION 'cannot restore a reversed application' USING ERRCODE = '23514';
    END IF;
    SELECT coalesce(sum(amount), 0) INTO allocated_to_refund
    FROM public.receivables_refundapplication
    WHERE organization_id = NEW.organization_id AND refund_id = NEW.refund_id;
    SELECT coalesce(sum(allocation.amount), 0) INTO restored_from_application
    FROM public.receivables_refundapplication allocation
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = allocation.organization_id
     AND reversal.target_kind = 'refund' AND reversal.target_id = allocation.refund_id
    WHERE allocation.organization_id = NEW.organization_id
      AND allocation.payment_application_id = NEW.payment_application_id
      AND reversal.id IS NULL;
    IF allocated_to_refund + NEW.amount > refund_row.amount THEN
        RAISE EXCEPTION 'refund allocations exceed refund' USING ERRCODE = '23514';
    END IF;
    IF restored_from_application + NEW.amount > application_row.amount THEN
        RAISE EXCEPTION 'refund exceeds payment application' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_application_due_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    current_revision integer;
    due_amount numeric(18,2);
    applied_amount numeric(18,2);
    restored_amount numeric(18,2);
BEGIN
    IF NEW.due_key IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT max(revision) INTO current_revision
    FROM public.receivables_collectionschedulerevision
    WHERE organization_id = NEW.organization_id AND obligation_id = NEW.obligation_id;
    SELECT due.amount INTO due_amount
    FROM public.receivables_collectionscheduledue due
    JOIN public.receivables_collectionschedulerevision revision
      ON revision.organization_id = due.organization_id
     AND revision.id = due.schedule_revision_id
    WHERE due.organization_id = NEW.organization_id
      AND due.obligation_id = NEW.obligation_id
      AND due.due_key = NEW.due_key
      AND revision.revision = current_revision;
    IF due_amount IS NULL THEN
        RAISE EXCEPTION 'application due is not in current schedule' USING ERRCODE = '23514';
    END IF;
    SELECT coalesce(sum(application.amount), 0) INTO applied_amount
    FROM public.receivables_paymentapplication application
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = application.organization_id
     AND reversal.target_kind = 'application' AND reversal.target_id = application.id
    WHERE application.organization_id = NEW.organization_id
      AND application.obligation_id = NEW.obligation_id
      AND application.due_key = NEW.due_key AND reversal.id IS NULL;
    SELECT coalesce(sum(allocation.amount), 0) INTO restored_amount
    FROM public.receivables_refundapplication allocation
    JOIN public.receivables_paymentapplication application
      ON application.organization_id = allocation.organization_id
     AND application.id = allocation.payment_application_id
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = allocation.organization_id
     AND reversal.target_kind = 'refund' AND reversal.target_id = allocation.refund_id
    WHERE allocation.organization_id = NEW.organization_id
      AND application.obligation_id = NEW.obligation_id
      AND application.due_key = NEW.due_key AND reversal.id IS NULL;
    IF applied_amount - restored_amount + NEW.amount > due_amount THEN
        RAISE EXCEPTION 'application exceeds current due balance' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_check_schedule_revision(
    target_organization uuid,
    target_revision uuid
) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    revision_row record;
    obligation_row record;
    due_count bigint;
    due_total numeric(18,2);
    adjusted_total numeric(18,2);
    mismatch_count bigint;
    invalid_application_count bigint;
BEGIN
    SELECT * INTO revision_row FROM public.receivables_collectionschedulerevision
    WHERE organization_id = target_organization AND id = target_revision;
    IF revision_row.id IS NULL THEN
        RETURN;
    END IF;
    SELECT * INTO obligation_row FROM public.receivables_receivableobligation
    WHERE organization_id = target_organization AND id = revision_row.obligation_id
    FOR UPDATE;
    SELECT count(*), coalesce(sum(amount), 0),
           count(*) FILTER (
               WHERE obligation_id <> revision_row.obligation_id
                  OR currency <> obligation_row.currency
           )
    INTO due_count, due_total, mismatch_count
    FROM public.receivables_collectionscheduledue
    WHERE organization_id = target_organization AND schedule_revision_id = target_revision;
    SELECT obligation_row.original_total
        + coalesce(sum(adjustment.amount) FILTER (
            WHERE adjustment.direction = 'increase' AND reversal.id IS NULL), 0)
        - coalesce(sum(adjustment.amount) FILTER (
            WHERE adjustment.direction = 'decrease' AND reversal.id IS NULL), 0)
    INTO adjusted_total
    FROM public.receivables_receivableadjustment adjustment
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = adjustment.organization_id
     AND reversal.target_kind = 'adjustment' AND reversal.target_id = adjustment.id
    WHERE adjustment.organization_id = target_organization
      AND adjustment.obligation_id = obligation_row.id
    GROUP BY obligation_row.original_total;
    adjusted_total := coalesce(adjusted_total, obligation_row.original_total);
    IF mismatch_count <> 0 OR (due_count <> 0 AND due_total <> adjusted_total) THEN
        RAISE EXCEPTION 'collection schedule revision is inconsistent' USING ERRCODE = '23514';
    END IF;
    IF revision_row.revision = (
        SELECT max(revision) FROM public.receivables_collectionschedulerevision
        WHERE organization_id = target_organization
          AND obligation_id = revision_row.obligation_id
    ) THEN
        SELECT count(*) INTO invalid_application_count
        FROM public.receivables_paymentapplication application
        LEFT JOIN public.receivables_movementreversal reversal
          ON reversal.organization_id = application.organization_id
         AND reversal.target_kind = 'application' AND reversal.target_id = application.id
        WHERE application.organization_id = target_organization
          AND application.obligation_id = revision_row.obligation_id
          AND application.due_key IS NOT NULL
          AND reversal.id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM public.receivables_collectionscheduledue due
              WHERE due.organization_id = target_organization
                AND due.schedule_revision_id = target_revision
                AND due.due_key = application.due_key
                AND due.amount >= application.amount - coalesce((
                    SELECT sum(allocation.amount)
                    FROM public.receivables_refundapplication allocation
                    LEFT JOIN public.receivables_movementreversal refund_reversal
                      ON refund_reversal.organization_id = allocation.organization_id
                     AND refund_reversal.target_kind = 'refund'
                     AND refund_reversal.target_id = allocation.refund_id
                    WHERE allocation.organization_id = target_organization
                      AND allocation.payment_application_id = application.id
                      AND refund_reversal.id IS NULL
                ), 0)
          );
        IF invalid_application_count <> 0 THEN
            RAISE EXCEPTION 'schedule revision contradicts existing applications'
                USING ERRCODE = '23514';
        END IF;
    END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_schedule_revision()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM public.claridez_receivables_check_schedule_revision(
            OLD.organization_id, OLD.schedule_revision_id
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM public.claridez_receivables_check_schedule_revision(
            NEW.organization_id, NEW.schedule_revision_id
        );
    END IF;
    RETURN NULL;
END;
$function$;

REVOKE ALL ON FUNCTION public.claridez_receivables_guard_reversal_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_refund_allocation_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_application_due_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_check_schedule_revision(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_schedule_revision() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_receivables_guard_reversal_insert(),
    public.claridez_receivables_guard_refund_allocation_insert(),
    public.claridez_receivables_guard_application_due_insert(),
    public.claridez_receivables_check_schedule_revision(uuid, uuid),
    public.claridez_receivables_guard_schedule_revision()
TO claridez_app, claridez_test_runner, claridez_migrator;

CREATE TRIGGER receivables_reversal_insert_guard
BEFORE INSERT ON public.receivables_movementreversal
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_reversal_insert();

CREATE TRIGGER receivables_refund_allocation_insert_guard
BEFORE INSERT ON public.receivables_refundapplication
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_refund_allocation_insert();

CREATE TRIGGER receivables_application_due_insert_guard
BEFORE INSERT ON public.receivables_paymentapplication
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_application_due_insert();

CREATE CONSTRAINT TRIGGER receivables_schedule_revision_guard
AFTER INSERT OR UPDATE OR DELETE ON public.receivables_collectionscheduledue
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_schedule_revision();
"""

GUARDS_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS receivables_schedule_revision_guard
ON public.receivables_collectionscheduledue;
DROP TRIGGER IF EXISTS receivables_refund_allocation_insert_guard
ON public.receivables_refundapplication;
DROP TRIGGER IF EXISTS receivables_application_due_insert_guard
ON public.receivables_paymentapplication;
DROP TRIGGER IF EXISTS receivables_reversal_insert_guard
ON public.receivables_movementreversal;
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_schedule_revision();
DROP FUNCTION IF EXISTS public.claridez_receivables_check_schedule_revision(uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_refund_allocation_insert();
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_application_due_insert();
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_reversal_insert();
ALTER TABLE public.receivables_movementreversal
DROP CONSTRAINT IF EXISTS recv_reversal_target_kind_ck;
"""


class Migration(migrations.Migration):
    dependencies = [("receivables", "0003_integrity_rls_and_guardians")]

    operations = [
        migrations.RunSQL(_currency_sql(), _currency_reverse_sql()),
        migrations.RunSQL(GUARDS_SQL, GUARDS_REVERSE_SQL),
    ]
