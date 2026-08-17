from django.db import migrations

SCHEDULE_CHECK_SQL = r"""
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
    IF mismatch_count <> 0 OR due_total > adjusted_total THEN
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
"""

ACTIVE_SCHEDULE_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_active_schedule()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_obligation uuid;
    target_revision uuid;
BEGIN
    IF TG_TABLE_NAME = 'receivables_receivableadjustment' THEN
        target_obligation := NEW.obligation_id;
    ELSIF NEW.target_kind = 'adjustment' THEN
        SELECT obligation_id INTO target_obligation
        FROM public.receivables_receivableadjustment
        WHERE organization_id = NEW.organization_id AND id = NEW.target_id;
    END IF;
    IF target_obligation IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT id INTO target_revision
    FROM public.receivables_collectionschedulerevision
    WHERE organization_id = NEW.organization_id AND obligation_id = target_obligation
    ORDER BY revision DESC, id DESC
    LIMIT 1;
    IF target_revision IS NOT NULL THEN
        PERFORM public.claridez_receivables_check_schedule_revision(
            NEW.organization_id, target_revision
        );
    END IF;
    RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_active_schedule() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_receivables_guard_active_schedule()
TO claridez_app, claridez_test_runner, claridez_migrator;

CREATE CONSTRAINT TRIGGER receivables_adjustment_schedule_guard
AFTER INSERT ON public.receivables_receivableadjustment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_active_schedule();

CREATE CONSTRAINT TRIGGER receivables_reversal_schedule_guard
AFTER INSERT ON public.receivables_movementreversal
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_active_schedule();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS receivables_reversal_schedule_guard
ON public.receivables_movementreversal;
DROP TRIGGER IF EXISTS receivables_adjustment_schedule_guard
ON public.receivables_receivableadjustment;
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_active_schedule();
""" + SCHEDULE_CHECK_SQL.replace(
    "mismatch_count <> 0 OR due_total > adjusted_total",
    "mismatch_count <> 0 OR (due_count <> 0 AND due_total <> adjusted_total)",
)


class Migration(migrations.Migration):
    dependencies = [("receivables", "0004_financial_guard_hardening")]

    operations = [
        migrations.RunSQL(
            SCHEDULE_CHECK_SQL + ACTIVE_SCHEDULE_GUARD_SQL,
            REVERSE_SQL,
        )
    ]
