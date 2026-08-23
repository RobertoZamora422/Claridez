# ruff: noqa: E501

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_finance_effective_source(
    target_organization uuid, target_kind text, target_id uuid
)
RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT CASE target_kind
        WHEN 'direct_cost' THEN (
            SELECT cost.amount
                 + coalesce(sum(correction.amount) FILTER (WHERE correction.direction = 'increase'), 0)
                 - coalesce(sum(correction.amount) FILTER (WHERE correction.direction = 'decrease'), 0)
            FROM public.finance_actualdirectcost cost
            LEFT JOIN public.finance_directcostcorrection correction
              ON correction.organization_id = cost.organization_id
             AND correction.direct_cost_id = cost.id
            WHERE cost.organization_id = target_organization AND cost.id = target_id
            GROUP BY cost.id
        )
        WHEN 'expense' THEN (
            SELECT expense.amount
                 + coalesce(sum(correction.amount) FILTER (WHERE correction.direction = 'increase'), 0)
                 - coalesce(sum(correction.amount) FILTER (WHERE correction.direction = 'decrease'), 0)
            FROM public.finance_expenseoccurrence expense
            LEFT JOIN public.finance_expenseoccurrencecorrection correction
              ON correction.organization_id = expense.organization_id
             AND correction.expense_occurrence_id = expense.id
            WHERE expense.organization_id = target_organization AND expense.id = target_id
            GROUP BY expense.id
        )
        ELSE NULL
    END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_effective_cash(
    target_organization uuid, target_id uuid
)
RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT movement.amount
         + coalesce(sum(correction.amount) FILTER (WHERE correction.direction = 'increase'), 0)
         - coalesce(sum(correction.amount) FILTER (WHERE correction.direction = 'decrease'), 0)
    FROM public.finance_operatingcashmovement movement
    LEFT JOIN public.finance_cashmovementcorrection correction
      ON correction.organization_id = movement.organization_id
     AND correction.cash_movement_id = movement.id
    WHERE movement.organization_id = target_organization AND movement.id = target_id
    GROUP BY movement.id;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_source_cash_net(
    target_organization uuid, target_kind text, target_id uuid
)
RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce(sum(
        CASE movement.direction
            WHEN 'outflow' THEN public.claridez_finance_effective_cash(
                movement.organization_id, movement.id
            )
            ELSE -public.claridez_finance_effective_cash(
                movement.organization_id, movement.id
            )
        END
    ), 0)
    FROM public.finance_operatingcashmovement movement
    WHERE movement.organization_id = target_organization
      AND movement.source_kind = target_kind
      AND movement.source_id = target_id;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_recovered_cash(
    target_organization uuid, target_outflow uuid
)
RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce(sum(public.claridez_finance_effective_cash(
        movement.organization_id, movement.id
    )), 0)
    FROM public.finance_operatingcashmovement movement
    WHERE movement.organization_id = target_organization
      AND movement.original_outflow_id = target_outflow
      AND movement.direction = 'recovery';
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_recognition_net(
    target_organization uuid, target_root uuid
)
RETURNS numeric LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce(sum(
        CASE adjustment.direction
            WHEN 'increase' THEN adjustment.amount
                + coalesce((SELECT sum(correction.amount)
                            FROM public.finance_recognitionadjustmentcorrection correction
                            WHERE correction.organization_id = adjustment.organization_id
                              AND correction.recognition_adjustment_id = adjustment.id
                              AND correction.direction = 'increase'), 0)
                - coalesce((SELECT sum(correction.amount)
                            FROM public.finance_recognitionadjustmentcorrection correction
                            WHERE correction.organization_id = adjustment.organization_id
                              AND correction.recognition_adjustment_id = adjustment.id
                              AND correction.direction = 'decrease'), 0)
            ELSE -(adjustment.amount
                + coalesce((SELECT sum(correction.amount)
                            FROM public.finance_recognitionadjustmentcorrection correction
                            WHERE correction.organization_id = adjustment.organization_id
                              AND correction.recognition_adjustment_id = adjustment.id
                              AND correction.direction = 'increase'), 0)
                - coalesce((SELECT sum(correction.amount)
                            FROM public.finance_recognitionadjustmentcorrection correction
                            WHERE correction.organization_id = adjustment.organization_id
                              AND correction.recognition_adjustment_id = adjustment.id
                              AND correction.direction = 'decrease'), 0))
        END
    ), 0)
    FROM public.finance_recognitionadjustment adjustment
    WHERE adjustment.organization_id = target_organization
      AND adjustment.root_reservation_id = target_root;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_recognition_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    sale_total numeric(18,2);
    sale_currency text;
    completion_date date;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':recognition:' || NEW.root_reservation_id::text,
        0
    ));
    SELECT obligation.original_total, obligation.currency
    INTO sale_total, sale_currency
    FROM public.receivables_receivableobligation obligation
    WHERE obligation.organization_id = NEW.organization_id
      AND obligation.root_reservation_id = NEW.root_reservation_id;
    SELECT (preparation.completed_at AT TIME ZONE settings.timezone)::date
    INTO completion_date
    FROM public.operations_eventpreparation preparation
    JOIN public.commercial_reservation reservation
      ON reservation.organization_id = preparation.organization_id
     AND reservation.id = preparation.reservation_id
    JOIN public.organizations_organizationsettings settings
      ON settings.organization_id = preparation.organization_id
    WHERE preparation.organization_id = NEW.organization_id
      AND reservation.root_id = NEW.root_reservation_id
      AND preparation.completed_at IS NOT NULL
    ORDER BY preparation.completed_at DESC, preparation.reservation_id DESC
    LIMIT 1;
    IF sale_total IS NULL OR completion_date IS NULL OR NEW.currency <> sale_currency
       OR NEW.economic_date < completion_date OR NEW.direction NOT IN ('increase', 'decrease')
       OR btrim(NEW.reason) = '' OR btrim(NEW.evidence_reference) = ''
       OR lower(NEW.reason) ~ '(cancel|penal|anticipo|deposit|cr[eé]dito|devolu|refund)'
       OR (
           NEW.direction = 'decrease'
           AND sale_total + public.claridez_finance_recognition_net(
               NEW.organization_id, NEW.root_reservation_id
           ) - NEW.amount < 0
       ) THEN
        RAISE EXCEPTION 'recognition adjustment is inconsistent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_open_period()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    target_period uuid;
    target_currency text;
    economic_period record;
    expected_registration uuid;
BEGIN
    IF TG_TABLE_NAME = 'finance_operatingbudgetrevision' THEN
        target_period := NEW.period_id;
    ELSE
        target_period := NEW.registration_period_id;
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':period:' || target_period::text,
        0
    ));
    SELECT period.currency INTO target_currency
    FROM public.finance_operationalperiod period
    WHERE period.organization_id = NEW.organization_id AND period.id = target_period;
    IF target_currency IS NULL OR EXISTS (
        SELECT 1 FROM public.finance_periodclosesnapshot close
        WHERE close.organization_id = NEW.organization_id AND close.period_id = target_period
    ) OR NEW.currency <> target_currency THEN
        RAISE EXCEPTION 'closed or inconsistent registration period' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'finance_operatingbudgetrevision' THEN
        RETURN NEW;
    END IF;
    SELECT period.* INTO economic_period
    FROM public.finance_operationalperiod period
    WHERE period.organization_id = NEW.organization_id
      AND period.starts_on <= NEW.economic_date
      AND period.ends_on > NEW.economic_date;
    IF economic_period.id IS NULL THEN
        RAISE EXCEPTION 'economic period is missing' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.finance_periodclosesnapshot close
        WHERE close.organization_id = NEW.organization_id
          AND close.period_id = economic_period.id
    ) THEN
        expected_registration := economic_period.id;
    ELSE
        SELECT period.id INTO expected_registration
        FROM public.finance_operationalperiod period
        WHERE period.organization_id = NEW.organization_id
          AND period.starts_on >= economic_period.ends_on
          AND NOT EXISTS (
              SELECT 1 FROM public.finance_periodclosesnapshot close
              WHERE close.organization_id = period.organization_id
                AND close.period_id = period.id
          )
        ORDER BY period.starts_on, period.id
        LIMIT 1;
    END IF;
    IF expected_registration IS NULL OR target_period <> expected_registration THEN
        RAISE EXCEPTION 'registration period does not match economic provenance'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_period_close_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    target_period record;
    organization_timezone text;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':period:' || NEW.period_id::text,
        0
    ));
    SELECT period.* INTO target_period
    FROM public.finance_operationalperiod period
    WHERE period.organization_id = NEW.organization_id AND period.id = NEW.period_id;
    SELECT settings.timezone INTO organization_timezone
    FROM public.organizations_organizationsettings settings
    WHERE settings.organization_id = NEW.organization_id;
    IF target_period.id IS NULL OR EXISTS (
        SELECT 1 FROM public.finance_periodclosesnapshot close
        WHERE close.organization_id = NEW.organization_id AND close.period_id = NEW.period_id
    ) OR EXISTS (
        SELECT 1 FROM public.finance_operationalperiod earlier
        WHERE earlier.organization_id = NEW.organization_id
          AND earlier.starts_on < target_period.starts_on
          AND NOT EXISTS (
              SELECT 1 FROM public.finance_periodclosesnapshot close
              WHERE close.organization_id = earlier.organization_id
                AND close.period_id = earlier.id
          )
    ) OR target_period.ends_on > (CURRENT_TIMESTAMP AT TIME ZONE organization_timezone)::date THEN
        RAISE EXCEPTION 'operational period cannot be closed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_cash_source()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    source_currency text;
    source_amount numeric(18,2);
    original_row record;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':cash:'
        || NEW.source_kind || ':' || NEW.source_id::text,
        0
    ));
    IF NEW.source_kind = 'direct_cost' THEN
        SELECT currency INTO source_currency
        FROM public.finance_actualdirectcost
        WHERE organization_id = NEW.organization_id AND id = NEW.source_id;
    ELSIF NEW.source_kind = 'expense' THEN
        SELECT currency INTO source_currency
        FROM public.finance_expenseoccurrence
        WHERE organization_id = NEW.organization_id AND id = NEW.source_id;
    ELSE
        RAISE EXCEPTION 'cash source kind is invalid' USING ERRCODE = '23514';
    END IF;
    source_amount := public.claridez_finance_effective_source(
        NEW.organization_id, NEW.source_kind, NEW.source_id
    );
    IF source_amount IS NULL OR NEW.currency <> source_currency THEN
        RAISE EXCEPTION 'cash source is inconsistent' USING ERRCODE = '23514';
    END IF;
    IF NEW.direction = 'outflow' THEN
        IF public.claridez_finance_source_cash_net(
            NEW.organization_id, NEW.source_kind, NEW.source_id
        ) + NEW.amount > source_amount THEN
            RAISE EXCEPTION 'cash outflow exceeds effective source' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO original_row
        FROM public.finance_operatingcashmovement
        WHERE organization_id = NEW.organization_id
          AND id = NEW.original_outflow_id
          AND direction = 'outflow'
          AND source_kind = NEW.source_kind
          AND source_id = NEW.source_id;
        IF original_row.id IS NULL OR public.claridez_finance_recovered_cash(
            NEW.organization_id, NEW.original_outflow_id
        ) + NEW.amount > public.claridez_finance_effective_cash(
            NEW.organization_id, NEW.original_outflow_id
        ) THEN
            RAISE EXCEPTION 'cash recovery exceeds effective outflow' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_typed_correction()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    target_amount numeric(18,2);
    target_currency text;
    increases numeric(18,2);
    decreases numeric(18,2);
    corrected_amount numeric(18,2);
    correction_effect numeric(18,2);
    target_source_kind text;
    target_source_id uuid;
    movement_direction text;
    original_outflow_id uuid;
    source_currency text;
    target_root uuid;
    target_direction text;
    sale_total numeric(18,2);
BEGIN
    correction_effect := CASE WHEN NEW.direction = 'increase' THEN NEW.amount ELSE -NEW.amount END;
    IF TG_TABLE_NAME = 'finance_directcostcorrection' THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
            'finance:' || NEW.organization_id::text || ':cash:direct_cost:'
            || NEW.direct_cost_id::text,
            0
        ));
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_actualdirectcost
        WHERE organization_id = NEW.organization_id AND id = NEW.direct_cost_id;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases
        FROM public.finance_directcostcorrection
        WHERE organization_id = NEW.organization_id AND direct_cost_id = NEW.direct_cost_id;
        corrected_amount := target_amount + increases - decreases + correction_effect;
        IF corrected_amount < public.claridez_finance_source_cash_net(
            NEW.organization_id, 'direct_cost', NEW.direct_cost_id
        ) THEN
            RAISE EXCEPTION 'direct cost correction would underfund cash' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'finance_expenseoccurrencecorrection' THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
            'finance:' || NEW.organization_id::text || ':cash:expense:'
            || NEW.expense_occurrence_id::text,
            0
        ));
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_expenseoccurrence
        WHERE organization_id = NEW.organization_id AND id = NEW.expense_occurrence_id;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases
        FROM public.finance_expenseoccurrencecorrection
        WHERE organization_id = NEW.organization_id
          AND expense_occurrence_id = NEW.expense_occurrence_id;
        corrected_amount := target_amount + increases - decreases + correction_effect;
        IF corrected_amount < public.claridez_finance_source_cash_net(
            NEW.organization_id, 'expense', NEW.expense_occurrence_id
        ) THEN
            RAISE EXCEPTION 'expense correction would underfund cash' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'finance_cashmovementcorrection' THEN
        SELECT movement.source_kind, movement.source_id, movement.direction,
               movement.original_outflow_id
        INTO target_source_kind, target_source_id, movement_direction, original_outflow_id
        FROM public.finance_operatingcashmovement movement
        WHERE movement.organization_id = NEW.organization_id
          AND movement.id = NEW.cash_movement_id;
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
            'finance:' || NEW.organization_id::text || ':cash:'
            || target_source_kind || ':' || target_source_id::text,
            0
        ));
        IF target_source_kind = 'direct_cost' THEN
            SELECT currency INTO source_currency
            FROM public.finance_actualdirectcost
            WHERE organization_id = NEW.organization_id AND id = target_source_id;
        ELSE
            SELECT currency INTO source_currency
            FROM public.finance_expenseoccurrence
            WHERE organization_id = NEW.organization_id AND id = target_source_id;
        END IF;
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_operatingcashmovement
        WHERE organization_id = NEW.organization_id AND id = NEW.cash_movement_id;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases
        FROM public.finance_cashmovementcorrection
        WHERE organization_id = NEW.organization_id AND cash_movement_id = NEW.cash_movement_id;
        corrected_amount := target_amount + increases - decreases + correction_effect;
        IF (
            public.claridez_finance_source_cash_net(
                NEW.organization_id, target_source_kind, target_source_id
            )
            + (CASE WHEN movement_direction = 'outflow'
                    THEN correction_effect ELSE -correction_effect END)
            > public.claridez_finance_effective_source(
                NEW.organization_id, target_source_kind, target_source_id
            )
        ) THEN
            RAISE EXCEPTION 'cash correction exceeds effective source' USING ERRCODE = '23514';
        END IF;
        IF movement_direction = 'outflow' AND public.claridez_finance_recovered_cash(
            NEW.organization_id, NEW.cash_movement_id
        ) > corrected_amount THEN
            RAISE EXCEPTION 'cash correction leaves recovery above outflow' USING ERRCODE = '23514';
        ELSIF movement_direction = 'recovery' AND public.claridez_finance_recovered_cash(
            NEW.organization_id, original_outflow_id
        ) + correction_effect > public.claridez_finance_effective_cash(
            NEW.organization_id, original_outflow_id
        ) THEN
            RAISE EXCEPTION 'cash correction makes recovery exceed outflow' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT root_reservation_id INTO target_root
        FROM public.finance_recognitionadjustment
        WHERE organization_id = NEW.organization_id AND id = NEW.recognition_adjustment_id;
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
            'finance:' || NEW.organization_id::text || ':recognition:' || target_root::text,
            0
        ));
        SELECT amount, currency, direction
        INTO target_amount, target_currency, target_direction
        FROM public.finance_recognitionadjustment
        WHERE organization_id = NEW.organization_id AND id = NEW.recognition_adjustment_id;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases
        FROM public.finance_recognitionadjustmentcorrection
        WHERE organization_id = NEW.organization_id
          AND recognition_adjustment_id = NEW.recognition_adjustment_id;
        corrected_amount := target_amount + increases - decreases + correction_effect;
        SELECT original_total INTO sale_total
        FROM public.receivables_receivableobligation
        WHERE organization_id = NEW.organization_id AND root_reservation_id = target_root;
        IF (
            sale_total + public.claridez_finance_recognition_net(
                NEW.organization_id, target_root
            ) + (CASE WHEN target_direction = 'increase'
                      THEN correction_effect ELSE -correction_effect END) < 0
        ) THEN
            RAISE EXCEPTION 'recognition correction makes revenue negative' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF target_amount IS NULL OR NEW.currency <> target_currency OR corrected_amount < 0 THEN
        RAISE EXCEPTION 'typed correction is inconsistent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION public.claridez_finance_effective_source(uuid, text, uuid),
    public.claridez_finance_effective_cash(uuid, uuid),
    public.claridez_finance_source_cash_net(uuid, text, uuid),
    public.claridez_finance_recovered_cash(uuid, uuid),
    public.claridez_finance_recognition_net(uuid, uuid),
    public.claridez_finance_guard_recognition_insert(),
    public.claridez_finance_guard_open_period(),
    public.claridez_finance_guard_period_close_insert(),
    public.claridez_finance_guard_cash_source(),
    public.claridez_finance_guard_typed_correction()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_finance_effective_source(uuid, text, uuid),
    public.claridez_finance_effective_cash(uuid, uuid),
    public.claridez_finance_source_cash_net(uuid, text, uuid),
    public.claridez_finance_recovered_cash(uuid, uuid),
    public.claridez_finance_recognition_net(uuid, uuid),
    public.claridez_finance_guard_recognition_insert(),
    public.claridez_finance_guard_open_period(),
    public.claridez_finance_guard_period_close_insert(),
    public.claridez_finance_guard_cash_source(),
    public.claridez_finance_guard_typed_correction()
TO claridez_app, claridez_test_runner, claridez_migrator;

ALTER TABLE public.finance_directcostcorrection
ADD CONSTRAINT finance_costcorr_direction_hard_ck CHECK (direction IN ('increase', 'decrease'));
ALTER TABLE public.finance_expenseoccurrencecorrection
ADD CONSTRAINT finance_expcorr_direction_hard_ck CHECK (direction IN ('increase', 'decrease'));
ALTER TABLE public.finance_cashmovementcorrection
ADD CONSTRAINT finance_cashcorr_direction_hard_ck CHECK (direction IN ('increase', 'decrease'));
ALTER TABLE public.finance_recognitionadjustment
ADD CONSTRAINT finance_recognition_direction_hard_ck CHECK (direction IN ('increase', 'decrease'));
ALTER TABLE public.finance_recognitionadjustmentcorrection
ADD CONSTRAINT finance_reccorr_direction_hard_ck CHECK (direction IN ('increase', 'decrease'));
ALTER TABLE public.finance_financecategory
ADD CONSTRAINT finance_category_kind_hard_ck
CHECK (kind IN ('direct_cost', 'variable_expense', 'recurring_expense'));
ALTER TABLE public.finance_expenseoccurrence
ADD CONSTRAINT finance_expense_type_hard_ck CHECK (expense_type IN ('variable', 'recurring'));

CREATE TRIGGER finance_recognition_integrity_guard
BEFORE INSERT ON public.finance_recognitionadjustment
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_recognition_insert();

CREATE TRIGGER finance_period_close_integrity_guard
BEFORE INSERT ON public.finance_periodclosesnapshot
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_period_close_insert();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS finance_period_close_integrity_guard
ON public.finance_periodclosesnapshot;
DROP TRIGGER IF EXISTS finance_recognition_integrity_guard
ON public.finance_recognitionadjustment;

ALTER TABLE public.finance_expenseoccurrence
DROP CONSTRAINT IF EXISTS finance_expense_type_hard_ck;
ALTER TABLE public.finance_financecategory
DROP CONSTRAINT IF EXISTS finance_category_kind_hard_ck;
ALTER TABLE public.finance_recognitionadjustmentcorrection
DROP CONSTRAINT IF EXISTS finance_reccorr_direction_hard_ck;
ALTER TABLE public.finance_recognitionadjustment
DROP CONSTRAINT IF EXISTS finance_recognition_direction_hard_ck;
ALTER TABLE public.finance_cashmovementcorrection
DROP CONSTRAINT IF EXISTS finance_cashcorr_direction_hard_ck;
ALTER TABLE public.finance_expenseoccurrencecorrection
DROP CONSTRAINT IF EXISTS finance_expcorr_direction_hard_ck;
ALTER TABLE public.finance_directcostcorrection
DROP CONSTRAINT IF EXISTS finance_costcorr_direction_hard_ck;

DROP FUNCTION IF EXISTS public.claridez_finance_guard_period_close_insert();
DROP FUNCTION IF EXISTS public.claridez_finance_guard_recognition_insert();
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("finance", "0003_deferred_guard_hardening")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
