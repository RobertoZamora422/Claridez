from django.db import migrations

PRIVATE_TABLES = (
    "receivables_receivableobligation",
    "receivables_collectionschedulerevision",
    "receivables_collectionscheduledue",
    "receivables_receivedpayment",
    "receivables_paymentapplication",
    "receivables_receivableadjustment",
    "receivables_movementreversal",
    "receivables_refundrecord",
    "receivables_refundapplication",
    "receivables_receipt",
    "receivables_receiptsequence",
    "receivables_financialcommand",
    "receivables_financialevent",
    "receivables_legacyevidencereview",
    "receivables_financialevidencelink",
)

IMMUTABLE_TABLES = tuple(
    table for table in PRIVATE_TABLES if table != "receivables_receiptsequence"
)

TENANT_FOREIGN_KEYS = (
    (
        "receivables_receivableobligation",
        "root_reservation_id",
        "commercial_reservation",
        "recv_obligation_root_fk",
    ),
    (
        "receivables_receivableobligation",
        "confirmation_source_id",
        "commercial_reservation",
        "recv_obligation_source_fk",
    ),
    (
        "receivables_receivableobligation",
        "confirmation_event_id",
        "scheduling_scheduleevent",
        "recv_obligation_event_fk",
    ),
    (
        "receivables_receivableobligation",
        "event_request_id",
        "commercial_eventrequest",
        "recv_obligation_request_fk",
    ),
    (
        "receivables_receivableobligation",
        "quotation_version_id",
        "commercial_quotationversion",
        "recv_obligation_quote_fk",
    ),
    (
        "receivables_receivableobligation",
        "counterparty_person_id",
        "commercial_person",
        "recv_obligation_person_fk",
    ),
    (
        "receivables_receivableobligation",
        "created_by_membership_id",
        "organizations_membership",
        "recv_obligation_actor_fk",
    ),
    (
        "receivables_collectionschedulerevision",
        "obligation_id",
        "receivables_receivableobligation",
        "recv_schedule_obligation_fk",
    ),
    (
        "receivables_collectionschedulerevision",
        "actor_membership_id",
        "organizations_membership",
        "recv_schedule_actor_fk",
    ),
    (
        "receivables_collectionscheduledue",
        "schedule_revision_id",
        "receivables_collectionschedulerevision",
        "recv_due_revision_fk",
    ),
    (
        "receivables_collectionscheduledue",
        "obligation_id",
        "receivables_receivableobligation",
        "recv_due_obligation_fk",
    ),
    (
        "receivables_receivedpayment",
        "root_reservation_id",
        "commercial_reservation",
        "recv_payment_root_fk",
    ),
    (
        "receivables_receivedpayment",
        "event_request_id",
        "commercial_eventrequest",
        "recv_payment_request_fk",
    ),
    (
        "receivables_receivedpayment",
        "counterparty_person_id",
        "commercial_person",
        "recv_payment_person_fk",
    ),
    (
        "receivables_receivedpayment",
        "confirmation_source_id",
        "commercial_reservation",
        "recv_payment_source_fk",
    ),
    (
        "receivables_receivedpayment",
        "recorded_by_membership_id",
        "organizations_membership",
        "recv_payment_actor_fk",
    ),
    (
        "receivables_paymentapplication",
        "payment_id",
        "receivables_receivedpayment",
        "recv_application_payment_fk",
    ),
    (
        "receivables_paymentapplication",
        "obligation_id",
        "receivables_receivableobligation",
        "recv_application_obligation_fk",
    ),
    (
        "receivables_paymentapplication",
        "applied_by_membership_id",
        "organizations_membership",
        "recv_application_actor_fk",
    ),
    (
        "receivables_receivableadjustment",
        "obligation_id",
        "receivables_receivableobligation",
        "recv_adjustment_obligation_fk",
    ),
    (
        "receivables_receivableadjustment",
        "recorded_by_membership_id",
        "organizations_membership",
        "recv_adjustment_actor_fk",
    ),
    (
        "receivables_movementreversal",
        "reversed_by_membership_id",
        "organizations_membership",
        "recv_reversal_actor_fk",
    ),
    (
        "receivables_refundrecord",
        "payment_id",
        "receivables_receivedpayment",
        "recv_refund_payment_fk",
    ),
    (
        "receivables_refundrecord",
        "obligation_id",
        "receivables_receivableobligation",
        "recv_refund_obligation_fk",
    ),
    (
        "receivables_refundrecord",
        "recorded_by_membership_id",
        "organizations_membership",
        "recv_refund_actor_fk",
    ),
    (
        "receivables_refundapplication",
        "refund_id",
        "receivables_refundrecord",
        "recv_refund_allocation_refund_fk",
    ),
    (
        "receivables_refundapplication",
        "payment_application_id",
        "receivables_paymentapplication",
        "recv_refund_allocation_application_fk",
    ),
    ("receivables_receipt", "payment_id", "receivables_receivedpayment", "recv_receipt_payment_fk"),
    (
        "receivables_receipt",
        "obligation_id",
        "receivables_receivableobligation",
        "recv_receipt_obligation_fk",
    ),
    (
        "receivables_receipt",
        "issued_by_membership_id",
        "organizations_membership",
        "recv_receipt_actor_fk",
    ),
    (
        "receivables_financialevent",
        "actor_membership_id",
        "organizations_membership",
        "recv_event_actor_fk",
    ),
    (
        "receivables_financialevidencelink",
        "linked_by_membership_id",
        "organizations_membership",
        "recv_evidence_actor_fk",
    ),
)

EXISTING_FORCE_RLS_TARGETS = (
    "commercial_reservation",
    "scheduling_scheduleevent",
    "commercial_eventrequest",
    "commercial_quotationversion",
    "commercial_person",
)


def _tenant_fk_sql() -> str:
    statements = [
        f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;"
        for table in EXISTING_FORCE_RLS_TARGETS
    ]
    for table, column, target, name in TENANT_FOREIGN_KEYS:
        statements.append(
            f"ALTER TABLE public.{table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY (organization_id, {column}) "
            f"REFERENCES public.{target} (organization_id, id);"
        )
    statements.extend(
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;"
        for table in reversed(EXISTING_FORCE_RLS_TARGETS)
    )
    return "\n".join(statements)


def _tenant_fk_reverse_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name};"
        for table, _, _, name in reversed(TENANT_FOREIGN_KEYS)
    )


def _rls_sql() -> str:
    statements: list[str] = []
    for table in PRIVATE_TABLES:
        policy = f"{table}_tenant_policy"
        statements.extend(
            [
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, claridez_app;",
                f"GRANT SELECT, INSERT ON TABLE public.{table} TO claridez_app;",
                (
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} "
                    "TO claridez_test_runner;"
                ),
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                f"DROP POLICY IF EXISTS {policy} ON public.{table};",
                f"CREATE POLICY {policy} ON public.{table} AS PERMISSIVE FOR ALL "
                "USING (organization_id = public.claridez_current_organization_id()) "
                "WITH CHECK (organization_id = public.claridez_current_organization_id());",
            ]
        )
    statements.extend(
        [
            "GRANT UPDATE ON TABLE public.receivables_receiptsequence TO claridez_app;",
            "REVOKE TRUNCATE ON TABLE "
            + ", ".join(f"public.{table}" for table in PRIVATE_TABLES)
            + " FROM claridez_app;",
        ]
    )
    return "\n".join(statements)


def _rls_reverse_sql() -> str:
    statements: list[str] = []
    for table in reversed(PRIVATE_TABLES):
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


IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION public.claridez_receivables_reject_history_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'receivables financial history is append-only' USING ERRCODE = '55000';
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_receivables_reject_history_change() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_receivables_reject_history_change()
TO claridez_app, claridez_test_runner, claridez_migrator;
""" + "\n".join(
    f"DROP TRIGGER IF EXISTS {table}_immutable ON public.{table};\n"
    f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} "
    "FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_reject_history_change();"
    for table in IMMUTABLE_TABLES
)

IMMUTABILITY_REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER IF EXISTS {table}_immutable ON public.{table};"
        for table in reversed(IMMUTABLE_TABLES)
    )
    + "\nDROP FUNCTION IF EXISTS public.claridez_receivables_reject_history_change();"
)

CONFIRMATION_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_receivables_check_confirmed_root(
    target_organization uuid,
    target_root uuid
) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    previous_organization text;
    is_confirmed boolean;
    obligation_count bigint;
    mismatch_count bigint;
BEGIN
    previous_organization := current_setting('claridez.organization_id', true);
    PERFORM set_config('claridez.organization_id', target_organization::text, true);
    SELECT EXISTS (
        SELECT 1 FROM public.commercial_reservation AS reservation
        WHERE reservation.organization_id = target_organization
          AND reservation.root_id = target_root
          AND reservation.confirmation_source_id IS NOT NULL
    ) INTO is_confirmed;
    SELECT count(*) FROM public.receivables_receivableobligation AS obligation
    WHERE obligation.organization_id = target_organization
      AND obligation.root_reservation_id = target_root
    INTO obligation_count;
    IF is_confirmed AND obligation_count <> 1 THEN
        RAISE EXCEPTION 'confirmed reservation root must have exactly one receivable obligation'
            USING ERRCODE = '23514';
    END IF;
    IF NOT is_confirmed AND obligation_count <> 0 THEN
        RAISE EXCEPTION 'unconfirmed reservation root cannot have a receivable obligation'
            USING ERRCODE = '23514';
    END IF;
    IF is_confirmed THEN
        SELECT count(*)
        FROM public.receivables_receivableobligation AS obligation
        JOIN public.commercial_reservation AS chain
          ON chain.organization_id = obligation.organization_id
         AND chain.root_id = obligation.root_reservation_id
         AND chain.confirmation_source_id IS NOT NULL
        JOIN public.commercial_reservation AS source
          ON source.organization_id = chain.organization_id
         AND source.id = chain.confirmation_source_id
        JOIN public.commercial_quotationversion AS quote
          ON quote.organization_id = source.organization_id
         AND quote.id = source.quotation_version_id
        JOIN public.commercial_quotation AS quotation
          ON quotation.organization_id = quote.organization_id
         AND quotation.id = quote.quotation_id
        LEFT JOIN public.scheduling_scheduleevent AS confirmation_event
          ON confirmation_event.organization_id = obligation.organization_id
         AND confirmation_event.id = obligation.confirmation_event_id
        WHERE obligation.organization_id = target_organization
          AND obligation.root_reservation_id = target_root
          AND (
              obligation.confirmation_source_id <> source.id
              OR obligation.event_request_id <> source.event_request_id
              OR obligation.quotation_version_id <> quote.id
              OR obligation.counterparty_person_id <> (
                  SELECT request.person_id
                  FROM public.commercial_eventrequest AS request
                  WHERE request.organization_id = quotation.organization_id
                    AND request.id = quotation.event_request_id
              )
              OR obligation.currency <> quote.currency
              OR obligation.subtotal <> quote.subtotal
              OR obligation.discount_total <> quote.discount_total
              OR obligation.original_total <> quote.total
              OR confirmation_event.id IS NULL
              OR confirmation_event.event_request_id IS DISTINCT FROM source.event_request_id
              OR confirmation_event.root_reservation_id IS DISTINCT FROM source.root_id
              OR confirmation_event.reservation_id IS DISTINCT FROM source.id
              OR NOT (
                  confirmation_event.kind = 'reservation_confirmed'
                  OR (
                      confirmation_event.kind = 'cutover_snapshot'
                      AND confirmation_event.source = 'cutover'
                      AND confirmation_event.new_snapshot ->> 'status'
                          IN ('confirmed', 'cancelled', 'rescheduled')
                      AND confirmation_event.new_snapshot ->> 'reservation_id' = source.id::text
                      AND confirmation_event.new_snapshot ->> 'root_id' = source.root_id::text
                  )
              )
          )
        INTO mismatch_count;
        IF mismatch_count <> 0 THEN
            RAISE EXCEPTION 'receivable obligation does not match confirmation source snapshot'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    PERFORM set_config('claridez.organization_id', coalesce(previous_organization, ''), true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('claridez.organization_id', coalesce(previous_organization, ''), true);
    RAISE;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_confirmation_root()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM public.claridez_receivables_check_confirmed_root(
            OLD.organization_id, OLD.root_id
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM public.claridez_receivables_check_confirmed_root(
            NEW.organization_id, NEW.root_id
        );
    END IF;
    RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_obligation_root()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM public.claridez_receivables_check_confirmed_root(
            OLD.organization_id, OLD.root_reservation_id
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM public.claridez_receivables_check_confirmed_root(
            NEW.organization_id, NEW.root_reservation_id
        );
    END IF;
    RETURN NULL;
END;
$function$;

REVOKE ALL ON FUNCTION public.claridez_receivables_check_confirmed_root(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_confirmation_root() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_obligation_root() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_receivables_check_confirmed_root(uuid, uuid),
    public.claridez_receivables_guard_confirmation_root(),
    public.claridez_receivables_guard_obligation_root()
TO claridez_app, claridez_test_runner, claridez_migrator;

DROP TRIGGER IF EXISTS scheduling_receivable_root_guard ON public.commercial_reservation;
CREATE CONSTRAINT TRIGGER scheduling_receivable_root_guard
AFTER INSERT OR UPDATE OR DELETE ON public.commercial_reservation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_confirmation_root();

DROP TRIGGER IF EXISTS receivables_confirmed_root_guard
ON public.receivables_receivableobligation;
CREATE CONSTRAINT TRIGGER receivables_confirmed_root_guard
AFTER INSERT OR UPDATE OR DELETE ON public.receivables_receivableobligation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_obligation_root();
"""

CONFIRMATION_GUARD_REVERSE_SQL = """
DROP TRIGGER IF EXISTS receivables_confirmed_root_guard
ON public.receivables_receivableobligation;
DROP TRIGGER IF EXISTS scheduling_receivable_root_guard ON public.commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_obligation_root();
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_confirmation_root();
DROP FUNCTION IF EXISTS public.claridez_receivables_check_confirmed_root(uuid, uuid);
"""

LEDGER_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_application_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    payment_row record;
    obligation_row record;
    payment_available numeric(18,2);
    obligation_balance numeric(18,2);
BEGIN
    SELECT * INTO obligation_row
    FROM public.receivables_receivableobligation
    WHERE organization_id = NEW.organization_id AND id = NEW.obligation_id
    FOR UPDATE;
    SELECT * INTO payment_row
    FROM public.receivables_receivedpayment
    WHERE organization_id = NEW.organization_id AND id = NEW.payment_id
    FOR UPDATE;
    IF obligation_row.id IS NULL OR payment_row.id IS NULL
       OR payment_row.currency <> obligation_row.currency
       OR NEW.currency <> obligation_row.currency
       OR payment_row.counterparty_person_id <> obligation_row.counterparty_person_id THEN
        RAISE EXCEPTION 'payment application context mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT payment_row.amount
        - coalesce(sum(application.amount) FILTER (
            WHERE reversal.id IS NULL AND payment_reversal.id IS NULL
          ), 0)
        - coalesce((SELECT sum(refund.amount)
            FROM public.receivables_refundrecord refund
            LEFT JOIN public.receivables_movementreversal rr
              ON rr.organization_id = refund.organization_id
             AND rr.target_kind = 'refund' AND rr.target_id = refund.id
            WHERE refund.organization_id = NEW.organization_id
              AND refund.payment_id = NEW.payment_id AND rr.id IS NULL), 0)
        + coalesce((SELECT sum(allocation.amount)
            FROM public.receivables_refundapplication allocation
            JOIN public.receivables_refundrecord refund ON refund.id = allocation.refund_id
            LEFT JOIN public.receivables_movementreversal rr
              ON rr.organization_id = refund.organization_id
             AND rr.target_kind = 'refund' AND rr.target_id = refund.id
            WHERE allocation.organization_id = NEW.organization_id
              AND allocation.payment_application_id IN (
                  SELECT id FROM public.receivables_paymentapplication
                  WHERE organization_id = NEW.organization_id
                    AND payment_id = NEW.payment_id
              ) AND rr.id IS NULL), 0)
    FROM public.receivables_paymentapplication application
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = application.organization_id
     AND reversal.target_kind = 'application' AND reversal.target_id = application.id
    LEFT JOIN public.receivables_movementreversal payment_reversal
      ON payment_reversal.organization_id = payment_row.organization_id
     AND payment_reversal.target_kind = 'payment'
     AND payment_reversal.target_id = payment_row.id
    WHERE application.organization_id = NEW.organization_id
      AND application.payment_id = NEW.payment_id
    GROUP BY payment_row.amount
    INTO payment_available;
    payment_available := coalesce(payment_available, payment_row.amount);
    SELECT obligation_row.original_total
        + coalesce(sum(adjustment.amount) FILTER (
            WHERE adjustment.direction = 'increase' AND reversal.id IS NULL
          ), 0)
        - coalesce(sum(adjustment.amount) FILTER (
            WHERE adjustment.direction = 'decrease' AND reversal.id IS NULL
          ), 0)
        - coalesce((SELECT sum(application.amount)
            FROM public.receivables_paymentapplication application
            LEFT JOIN public.receivables_movementreversal ar
              ON ar.organization_id = application.organization_id
             AND ar.target_kind = 'application' AND ar.target_id = application.id
            WHERE application.organization_id = NEW.organization_id
              AND application.obligation_id = NEW.obligation_id AND ar.id IS NULL), 0)
        + coalesce((SELECT sum(allocation.amount)
            FROM public.receivables_refundapplication allocation
            JOIN public.receivables_paymentapplication application
              ON application.id = allocation.payment_application_id
            LEFT JOIN public.receivables_movementreversal rr
              ON rr.organization_id = allocation.organization_id
             AND rr.target_kind = 'refund' AND rr.target_id = allocation.refund_id
            WHERE allocation.organization_id = NEW.organization_id
              AND application.obligation_id = NEW.obligation_id AND rr.id IS NULL), 0)
    FROM public.receivables_receivableadjustment adjustment
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = adjustment.organization_id
     AND reversal.target_kind = 'adjustment' AND reversal.target_id = adjustment.id
    WHERE adjustment.organization_id = NEW.organization_id
      AND adjustment.obligation_id = NEW.obligation_id
    GROUP BY obligation_row.original_total
    INTO obligation_balance;
    obligation_balance := coalesce(obligation_balance, obligation_row.original_total);
    IF NEW.amount > payment_available THEN
        RAISE EXCEPTION 'payment would be overallocated' USING ERRCODE = '23514';
    END IF;
    IF NEW.amount > obligation_balance THEN
        RAISE EXCEPTION 'obligation would be overallocated' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_refund_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    payment_row record;
    refunded numeric(18,2);
BEGIN
    IF NEW.obligation_id IS NOT NULL THEN
        PERFORM 1 FROM public.receivables_receivableobligation
        WHERE organization_id = NEW.organization_id AND id = NEW.obligation_id FOR UPDATE;
    END IF;
    SELECT * INTO payment_row FROM public.receivables_receivedpayment
    WHERE organization_id = NEW.organization_id AND id = NEW.payment_id FOR UPDATE;
    IF payment_row.id IS NULL OR payment_row.currency <> NEW.currency THEN
        RAISE EXCEPTION 'refund context mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT coalesce(sum(refund.amount), 0) INTO refunded
    FROM public.receivables_refundrecord refund
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.organization_id = refund.organization_id
     AND reversal.target_kind = 'refund' AND reversal.target_id = refund.id
    WHERE refund.organization_id = NEW.organization_id
      AND refund.payment_id = NEW.payment_id AND reversal.id IS NULL;
    IF refunded + NEW.amount > payment_row.amount THEN
        RAISE EXCEPTION 'refund exceeds received payment' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_receivables_guard_adjustment_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    obligation_row record;
    current_balance numeric(18,2);
BEGIN
    SELECT * INTO obligation_row FROM public.receivables_receivableobligation
    WHERE organization_id = NEW.organization_id AND id = NEW.obligation_id FOR UPDATE;
    IF obligation_row.id IS NULL OR obligation_row.currency <> NEW.currency THEN
        RAISE EXCEPTION 'adjustment context mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT obligation_row.original_total
        + coalesce(sum(adjustment.amount) FILTER (WHERE adjustment.direction = 'increase'), 0)
        - coalesce(sum(adjustment.amount) FILTER (WHERE adjustment.direction = 'decrease'), 0)
        - coalesce((SELECT sum(application.amount)
          FROM public.receivables_paymentapplication application
          LEFT JOIN public.receivables_movementreversal reversal
            ON reversal.target_kind = 'application' AND reversal.target_id = application.id
           AND reversal.organization_id = application.organization_id
          WHERE application.organization_id = NEW.organization_id
            AND application.obligation_id = NEW.obligation_id AND reversal.id IS NULL), 0)
    INTO current_balance
    FROM public.receivables_receivableadjustment adjustment
    LEFT JOIN public.receivables_movementreversal reversal
      ON reversal.target_kind = 'adjustment' AND reversal.target_id = adjustment.id
     AND reversal.organization_id = adjustment.organization_id
    WHERE adjustment.organization_id = NEW.organization_id
      AND adjustment.obligation_id = NEW.obligation_id AND reversal.id IS NULL
    GROUP BY obligation_row.original_total;
    current_balance := coalesce(current_balance, obligation_row.original_total);
    IF NEW.direction = 'decrease' AND NEW.amount > current_balance THEN
        RAISE EXCEPTION 'adjustment would make balance negative' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION public.claridez_receivables_guard_application_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_refund_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_receivables_guard_adjustment_insert() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_receivables_guard_application_insert(),
    public.claridez_receivables_guard_refund_insert(),
    public.claridez_receivables_guard_adjustment_insert()
TO claridez_app, claridez_test_runner, claridez_migrator;

DROP TRIGGER IF EXISTS receivables_application_insert_guard
ON public.receivables_paymentapplication;
CREATE TRIGGER receivables_application_insert_guard
BEFORE INSERT ON public.receivables_paymentapplication
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_application_insert();

DROP TRIGGER IF EXISTS receivables_refund_insert_guard ON public.receivables_refundrecord;
CREATE TRIGGER receivables_refund_insert_guard
BEFORE INSERT ON public.receivables_refundrecord
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_refund_insert();

DROP TRIGGER IF EXISTS receivables_adjustment_insert_guard
ON public.receivables_receivableadjustment;
CREATE TRIGGER receivables_adjustment_insert_guard
BEFORE INSERT ON public.receivables_receivableadjustment
FOR EACH ROW EXECUTE FUNCTION public.claridez_receivables_guard_adjustment_insert();
"""

LEDGER_GUARD_REVERSE_SQL = """
DROP TRIGGER IF EXISTS receivables_adjustment_insert_guard
ON public.receivables_receivableadjustment;
DROP TRIGGER IF EXISTS receivables_refund_insert_guard ON public.receivables_refundrecord;
DROP TRIGGER IF EXISTS receivables_application_insert_guard
ON public.receivables_paymentapplication;
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_adjustment_insert();
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_refund_insert();
DROP FUNCTION IF EXISTS public.claridez_receivables_guard_application_insert();
"""


class Migration(migrations.Migration):
    dependencies = [("receivables", "0002_backfill_p9_financial_history")]

    operations = [
        migrations.RunSQL(_tenant_fk_sql(), _tenant_fk_reverse_sql()),
        migrations.RunSQL(_rls_sql(), _rls_reverse_sql()),
        migrations.RunSQL(IMMUTABILITY_SQL, IMMUTABILITY_REVERSE_SQL),
        migrations.RunSQL(LEDGER_GUARD_SQL, LEDGER_GUARD_REVERSE_SQL),
        migrations.RunSQL(CONFIRMATION_GUARD_SQL, CONFIRMATION_GUARD_REVERSE_SQL),
    ]
