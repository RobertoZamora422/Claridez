# ruff: noqa: E501

from django.db import migrations

PRIVATE_TABLES = (
    "finance_financecategory",
    "finance_operationalperiod",
    "finance_periodclosesnapshot",
    "finance_directcostplanrevision",
    "finance_directcostplanline",
    "finance_operationalcostevidence",
    "finance_evidencedecision",
    "finance_actualdirectcost",
    "finance_directcostcorrection",
    "finance_recurringexpenserule",
    "finance_expenseoccurrence",
    "finance_expenseallocation",
    "finance_expenseoccurrencecorrection",
    "finance_operatingbudgetrevision",
    "finance_operatingbudgetline",
    "finance_operatingcashmovement",
    "finance_cashmovementcorrection",
    "finance_recognitionadjustment",
    "finance_recognitionadjustmentcorrection",
    "finance_financecommand",
)

CURRENCY_TABLES = (
    "finance_operationalperiod",
    "finance_directcostplanrevision",
    "finance_directcostplanline",
    "finance_operationalcostevidence",
    "finance_actualdirectcost",
    "finance_directcostcorrection",
    "finance_recurringexpenserule",
    "finance_expenseoccurrence",
    "finance_expenseallocation",
    "finance_expenseoccurrencecorrection",
    "finance_operatingbudgetrevision",
    "finance_operatingbudgetline",
    "finance_operatingcashmovement",
    "finance_cashmovementcorrection",
    "finance_recognitionadjustment",
    "finance_recognitionadjustmentcorrection",
)

TENANT_FOREIGN_KEYS = (
    (
        "finance_financecategory",
        "created_by_membership_id",
        "organizations_membership",
        "fin_cat_actor_fk",
    ),
    (
        "finance_operationalperiod",
        "created_by_membership_id",
        "organizations_membership",
        "fin_period_actor_fk",
    ),
    (
        "finance_periodclosesnapshot",
        "period_id",
        "finance_operationalperiod",
        "fin_close_period_fk",
    ),
    (
        "finance_periodclosesnapshot",
        "closed_by_membership_id",
        "organizations_membership",
        "fin_close_actor_fk",
    ),
    (
        "finance_directcostplanrevision",
        "root_reservation_id",
        "commercial_reservation",
        "fin_plan_root_fk",
    ),
    ("finance_directcostplanrevision", "venue_id", "organizations_venue", "fin_plan_venue_fk"),
    (
        "finance_directcostplanrevision",
        "published_by_membership_id",
        "organizations_membership",
        "fin_plan_actor_fk",
    ),
    (
        "finance_directcostplanline",
        "plan_revision_id",
        "finance_directcostplanrevision",
        "fin_planline_plan_fk",
    ),
    ("finance_directcostplanline", "category_id", "finance_financecategory", "fin_planline_cat_fk"),
    (
        "finance_operationalcostevidence",
        "root_reservation_id",
        "commercial_reservation",
        "fin_evidence_root_fk",
    ),
    ("finance_operationalcostevidence", "venue_id", "organizations_venue", "fin_evidence_venue_fk"),
    (
        "finance_operationalcostevidence",
        "category_id",
        "finance_financecategory",
        "fin_evidence_cat_fk",
    ),
    (
        "finance_operationalcostevidence",
        "submitted_by_membership_id",
        "organizations_membership",
        "fin_evidence_actor_fk",
    ),
    (
        "finance_evidencedecision",
        "evidence_id",
        "finance_operationalcostevidence",
        "fin_decision_evidence_fk",
    ),
    (
        "finance_evidencedecision",
        "decided_by_membership_id",
        "organizations_membership",
        "fin_decision_actor_fk",
    ),
    (
        "finance_actualdirectcost",
        "root_reservation_id",
        "commercial_reservation",
        "fin_cost_root_fk",
    ),
    ("finance_actualdirectcost", "venue_id", "organizations_venue", "fin_cost_venue_fk"),
    ("finance_actualdirectcost", "category_id", "finance_financecategory", "fin_cost_cat_fk"),
    (
        "finance_actualdirectcost",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_cost_period_fk",
    ),
    (
        "finance_actualdirectcost",
        "source_evidence_id",
        "finance_operationalcostevidence",
        "fin_cost_evidence_fk",
    ),
    (
        "finance_actualdirectcost",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_cost_actor_fk",
    ),
    (
        "finance_directcostcorrection",
        "direct_cost_id",
        "finance_actualdirectcost",
        "fin_costcorr_cost_fk",
    ),
    (
        "finance_directcostcorrection",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_costcorr_period_fk",
    ),
    (
        "finance_directcostcorrection",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_costcorr_actor_fk",
    ),
    ("finance_recurringexpenserule", "category_id", "finance_financecategory", "fin_rule_cat_fk"),
    (
        "finance_recurringexpenserule",
        "default_venue_id",
        "organizations_venue",
        "fin_rule_venue_fk",
    ),
    (
        "finance_recurringexpenserule",
        "created_by_membership_id",
        "organizations_membership",
        "fin_rule_actor_fk",
    ),
    ("finance_expenseoccurrence", "category_id", "finance_financecategory", "fin_expense_cat_fk"),
    (
        "finance_expenseoccurrence",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_expense_period_fk",
    ),
    (
        "finance_expenseoccurrence",
        "recurring_rule_id",
        "finance_recurringexpenserule",
        "fin_expense_rule_fk",
    ),
    (
        "finance_expenseoccurrence",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_expense_actor_fk",
    ),
    (
        "finance_expenseallocation",
        "expense_occurrence_id",
        "finance_expenseoccurrence",
        "fin_alloc_expense_fk",
    ),
    (
        "finance_expenseallocation",
        "root_reservation_id",
        "commercial_reservation",
        "fin_alloc_root_fk",
    ),
    ("finance_expenseallocation", "venue_id", "organizations_venue", "fin_alloc_venue_fk"),
    (
        "finance_expenseoccurrencecorrection",
        "expense_occurrence_id",
        "finance_expenseoccurrence",
        "fin_expcorr_expense_fk",
    ),
    (
        "finance_expenseoccurrencecorrection",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_expcorr_period_fk",
    ),
    (
        "finance_expenseoccurrencecorrection",
        "root_reservation_id",
        "commercial_reservation",
        "fin_expcorr_root_fk",
    ),
    (
        "finance_expenseoccurrencecorrection",
        "venue_id",
        "organizations_venue",
        "fin_expcorr_venue_fk",
    ),
    (
        "finance_expenseoccurrencecorrection",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_expcorr_actor_fk",
    ),
    (
        "finance_operatingbudgetrevision",
        "period_id",
        "finance_operationalperiod",
        "fin_budget_period_fk",
    ),
    ("finance_operatingbudgetrevision", "venue_id", "organizations_venue", "fin_budget_venue_fk"),
    (
        "finance_operatingbudgetrevision",
        "published_by_membership_id",
        "organizations_membership",
        "fin_budget_actor_fk",
    ),
    (
        "finance_operatingbudgetline",
        "budget_revision_id",
        "finance_operatingbudgetrevision",
        "fin_budgetline_budget_fk",
    ),
    (
        "finance_operatingbudgetline",
        "category_id",
        "finance_financecategory",
        "fin_budgetline_cat_fk",
    ),
    (
        "finance_operatingcashmovement",
        "original_outflow_id",
        "finance_operatingcashmovement",
        "fin_cash_outflow_fk",
    ),
    (
        "finance_operatingcashmovement",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_cash_period_fk",
    ),
    (
        "finance_operatingcashmovement",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_cash_actor_fk",
    ),
    (
        "finance_cashmovementcorrection",
        "cash_movement_id",
        "finance_operatingcashmovement",
        "fin_cashcorr_cash_fk",
    ),
    (
        "finance_cashmovementcorrection",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_cashcorr_period_fk",
    ),
    (
        "finance_cashmovementcorrection",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_cashcorr_actor_fk",
    ),
    (
        "finance_recognitionadjustment",
        "root_reservation_id",
        "commercial_reservation",
        "fin_recognition_root_fk",
    ),
    (
        "finance_recognitionadjustment",
        "venue_id",
        "organizations_venue",
        "fin_recognition_venue_fk",
    ),
    (
        "finance_recognitionadjustment",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_recognition_period_fk",
    ),
    (
        "finance_recognitionadjustment",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_recognition_actor_fk",
    ),
    (
        "finance_recognitionadjustmentcorrection",
        "recognition_adjustment_id",
        "finance_recognitionadjustment",
        "fin_reccorr_recognition_fk",
    ),
    (
        "finance_recognitionadjustmentcorrection",
        "registration_period_id",
        "finance_operationalperiod",
        "fin_reccorr_period_fk",
    ),
    (
        "finance_recognitionadjustmentcorrection",
        "recorded_by_membership_id",
        "organizations_membership",
        "fin_reccorr_actor_fk",
    ),
)


def _tenant_fk_sql() -> str:
    statements = []
    for table, column, target, name in TENANT_FOREIGN_KEYS:
        statements.append(
            f"ALTER TABLE public.{table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY (organization_id, {column}) "
            f"REFERENCES public.{target} (organization_id, id);"
        )
    return "\n".join(statements)


def _tenant_fk_reverse_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name};"
        for table, _, _, name in reversed(TENANT_FOREIGN_KEYS)
    )


def _currency_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} ADD CONSTRAINT {table}_currency_ck "
        "CHECK (currency ~ '^[A-Z]{3}$');"
        for table in CURRENCY_TABLES
    )


def _currency_reverse_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {table}_currency_ck;"
        for table in reversed(CURRENCY_TABLES)
    )


def _rls_sql() -> str:
    statements = []
    for table in PRIVATE_TABLES:
        policy = f"{table}_tenant_policy"
        statements.extend(
            [
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, claridez_app;",
                f"GRANT SELECT, INSERT ON TABLE public.{table} TO claridez_app;",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO claridez_test_runner;",
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                f"CREATE POLICY {policy} ON public.{table} AS PERMISSIVE FOR ALL "
                "USING (organization_id = public.claridez_current_organization_id()) "
                "WITH CHECK (organization_id = public.claridez_current_organization_id());",
            ]
        )
    statements.append(
        "REVOKE TRUNCATE ON TABLE "
        + ", ".join(f"public.{table}" for table in PRIVATE_TABLES)
        + " FROM claridez_app;"
    )
    return "\n".join(statements)


def _rls_reverse_sql() -> str:
    statements = []
    for table in reversed(PRIVATE_TABLES):
        statements.extend(
            [
                f"DROP POLICY IF EXISTS {table}_tenant_policy ON public.{table};",
                f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;",
                f"REVOKE ALL ON TABLE public.{table} FROM claridez_app;",
            ]
        )
    return "\n".join(statements)


IMMUTABILITY_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_finance_reject_history_change()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    RAISE EXCEPTION 'finance history is append-only' USING ERRCODE = '55000';
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_finance_reject_history_change() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_finance_reject_history_change()
TO claridez_app, claridez_test_runner, claridez_migrator;
""" + "\n".join(
    f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} "
    "FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_reject_history_change();"
    for table in PRIVATE_TABLES
)

IMMUTABILITY_REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER IF EXISTS {table}_immutable ON public.{table};"
        for table in reversed(PRIVATE_TABLES)
    )
    + "\nDROP FUNCTION IF EXISTS public.claridez_finance_reject_history_change();"
)

GUARD_SQL = (
    r"""
ALTER TABLE public.finance_operationalperiod
ADD CONSTRAINT finance_period_no_overlap
EXCLUDE USING gist (
    organization_id WITH =,
    daterange(starts_on, ends_on, '[)') WITH &&
);

CREATE OR REPLACE FUNCTION public.claridez_finance_root_has_venue(
    target_organization uuid, target_root uuid, target_venue uuid
) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.commercial_reservation reservation
        JOIN public.organizations_space space
          ON space.organization_id = reservation.organization_id
         AND space.id = reservation.space_id
        WHERE reservation.organization_id = target_organization
          AND reservation.root_id = target_root
          AND space.venue_id = target_venue
    );
$function$;
REVOKE ALL ON FUNCTION public.claridez_finance_root_has_venue(uuid, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_finance_root_has_venue(uuid, uuid, uuid)
TO claridez_app, claridez_test_runner, claridez_migrator;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_root_venue()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_root uuid; target_venue uuid;
BEGIN
    IF TG_TABLE_NAME = 'finance_directcostplanrevision' THEN
        target_root := NEW.root_reservation_id; target_venue := NEW.venue_id;
        IF EXISTS (
            SELECT 1 FROM public.operations_eventpreparation preparation
            JOIN public.commercial_reservation reservation
              ON reservation.organization_id = preparation.organization_id
             AND reservation.id = preparation.reservation_id
            WHERE preparation.organization_id = NEW.organization_id
              AND reservation.root_id = NEW.root_reservation_id
              AND preparation.started_at IS NOT NULL
              AND NEW.published_at > preparation.started_at
        ) THEN
            RAISE EXCEPTION 'direct cost baseline is already frozen' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'finance_operationalcostevidence' THEN
        target_root := NEW.root_reservation_id; target_venue := NEW.venue_id;
    ELSIF TG_TABLE_NAME = 'finance_actualdirectcost' THEN
        target_root := NEW.root_reservation_id; target_venue := NEW.venue_id;
    ELSIF TG_TABLE_NAME = 'finance_expenseallocation' THEN
        target_root := NEW.root_reservation_id; target_venue := NEW.venue_id;
    ELSIF TG_TABLE_NAME = 'finance_expenseoccurrencecorrection' THEN
        target_root := NEW.root_reservation_id; target_venue := NEW.venue_id;
    ELSE
        target_root := NEW.root_reservation_id; target_venue := NEW.venue_id;
        IF NOT EXISTS (
            SELECT 1 FROM public.operations_eventpreparation preparation
            JOIN public.commercial_reservation reservation
              ON reservation.organization_id = preparation.organization_id
             AND reservation.id = preparation.reservation_id
            JOIN public.organizations_space space
              ON space.organization_id = reservation.organization_id
             AND space.id = reservation.space_id
            WHERE preparation.organization_id = NEW.organization_id
              AND reservation.root_id = NEW.root_reservation_id
              AND preparation.completed_at IS NOT NULL
              AND space.venue_id = NEW.venue_id
        ) THEN
            RAISE EXCEPTION 'recognition requires completed execution venue' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF target_root IS NOT NULL AND NOT public.claridez_finance_root_has_venue(
        NEW.organization_id, target_root, target_venue
    ) THEN
        RAISE EXCEPTION 'venue is not in reservation root history' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE TRIGGER finance_plan_root_venue_guard BEFORE INSERT ON public.finance_directcostplanrevision
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_root_venue();
CREATE TRIGGER finance_evidence_root_venue_guard BEFORE INSERT ON public.finance_operationalcostevidence
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_root_venue();
CREATE TRIGGER finance_cost_root_venue_guard BEFORE INSERT ON public.finance_actualdirectcost
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_root_venue();
CREATE TRIGGER finance_alloc_root_venue_guard BEFORE INSERT ON public.finance_expenseallocation
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_root_venue();
CREATE TRIGGER finance_expcorr_root_venue_guard BEFORE INSERT ON public.finance_expenseoccurrencecorrection
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_root_venue();
CREATE TRIGGER finance_recognition_root_venue_guard BEFORE INSERT ON public.finance_recognitionadjustment
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_root_venue();

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_open_period()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_period uuid;
BEGIN
    IF TG_TABLE_NAME = 'finance_operatingbudgetrevision' THEN
        target_period := NEW.period_id;
    ELSE
        target_period := NEW.registration_period_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.finance_periodclosesnapshot close
        WHERE close.organization_id = NEW.organization_id AND close.period_id = target_period
    ) THEN
        RAISE EXCEPTION 'closed period cannot receive facts' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
"""
    + "\n".join(
        f"CREATE TRIGGER {table}_open_period_guard BEFORE INSERT ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_open_period();"
        for table in (
            "finance_actualdirectcost",
            "finance_directcostcorrection",
            "finance_expenseoccurrence",
            "finance_expenseoccurrencecorrection",
            "finance_operatingbudgetrevision",
            "finance_operatingcashmovement",
            "finance_cashmovementcorrection",
            "finance_recognitionadjustment",
            "finance_recognitionadjustmentcorrection",
        )
    )
    + r"""

CREATE OR REPLACE FUNCTION public.claridez_finance_check_plan(target_organization uuid, target_plan uuid)
RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE invalid_count bigint; line_count bigint;
BEGIN
    SELECT count(line.id), count(*) FILTER (
        WHERE category.kind <> 'direct_cost' OR line.currency <> plan.currency
           OR line.organization_id <> plan.organization_id
    )
    INTO line_count, invalid_count
    FROM public.finance_directcostplanrevision plan
    LEFT JOIN public.finance_directcostplanline line
      ON line.organization_id = plan.organization_id AND line.plan_revision_id = plan.id
    LEFT JOIN public.finance_financecategory category
      ON category.organization_id = line.organization_id AND category.id = line.category_id
    WHERE plan.organization_id = target_organization AND plan.id = target_plan
    GROUP BY plan.id;
    IF line_count = 0 OR invalid_count <> 0 THEN
        RAISE EXCEPTION 'direct cost plan lines are inconsistent' USING ERRCODE = '23514';
    END IF;
END;
$function$;
CREATE OR REPLACE FUNCTION public.claridez_finance_plan_deferred_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_plan uuid;
BEGIN
    IF TG_TABLE_NAME = 'finance_directcostplanline' THEN
        target_plan := NEW.plan_revision_id;
    ELSE
        target_plan := NEW.id;
    END IF;
    PERFORM public.claridez_finance_check_plan(NEW.organization_id, target_plan);
    RETURN NULL;
END;
$function$;
CREATE CONSTRAINT TRIGGER finance_plan_revision_complete
AFTER INSERT ON public.finance_directcostplanrevision DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_plan_deferred_guard();
CREATE CONSTRAINT TRIGGER finance_plan_line_complete
AFTER INSERT ON public.finance_directcostplanline DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_plan_deferred_guard();

CREATE OR REPLACE FUNCTION public.claridez_finance_check_expense(target_organization uuid, target_expense uuid)
RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE expense_row record; allocated numeric(18,2); invalid_count bigint;
BEGIN
    SELECT * INTO expense_row FROM public.finance_expenseoccurrence
    WHERE organization_id = target_organization AND id = target_expense;
    IF expense_row.id IS NULL THEN RETURN; END IF;
    SELECT coalesce(sum(allocation.amount), 0), count(*) FILTER (
        WHERE allocation.currency <> expense_row.currency
           OR allocation.organization_id <> expense_row.organization_id
    ) INTO allocated, invalid_count
    FROM public.finance_expenseallocation allocation
    WHERE allocation.organization_id = target_organization
      AND allocation.expense_occurrence_id = target_expense;
    IF allocated <> expense_row.amount OR invalid_count <> 0 THEN
        RAISE EXCEPTION 'expense allocations must equal occurrence amount' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.finance_financecategory category
        WHERE category.organization_id = expense_row.organization_id
          AND category.id = expense_row.category_id
          AND category.kind = CASE expense_row.expense_type
              WHEN 'variable' THEN 'variable_expense' ELSE 'recurring_expense' END
    ) THEN
        RAISE EXCEPTION 'expense category mismatch' USING ERRCODE = '23514';
    END IF;
END;
$function$;
CREATE OR REPLACE FUNCTION public.claridez_finance_expense_deferred_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_expense uuid;
BEGIN
    IF TG_TABLE_NAME = 'finance_expenseallocation' THEN
        target_expense := NEW.expense_occurrence_id;
    ELSE
        target_expense := NEW.id;
    END IF;
    PERFORM public.claridez_finance_check_expense(NEW.organization_id, target_expense);
    RETURN NULL;
END;
$function$;
CREATE CONSTRAINT TRIGGER finance_expense_complete
AFTER INSERT ON public.finance_expenseoccurrence DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_expense_deferred_guard();
CREATE CONSTRAINT TRIGGER finance_allocation_complete
AFTER INSERT ON public.finance_expenseallocation DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_expense_deferred_guard();

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_typed_correction()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_amount numeric(18,2); target_currency text; increases numeric(18,2); decreases numeric(18,2);
BEGIN
    IF TG_TABLE_NAME = 'finance_directcostcorrection' THEN
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_actualdirectcost
        WHERE organization_id = NEW.organization_id AND id = NEW.direct_cost_id FOR UPDATE;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases FROM public.finance_directcostcorrection
        WHERE organization_id = NEW.organization_id AND direct_cost_id = NEW.direct_cost_id;
    ELSIF TG_TABLE_NAME = 'finance_expenseoccurrencecorrection' THEN
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_expenseoccurrence
        WHERE organization_id = NEW.organization_id AND id = NEW.expense_occurrence_id FOR UPDATE;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases FROM public.finance_expenseoccurrencecorrection
        WHERE organization_id = NEW.organization_id AND expense_occurrence_id = NEW.expense_occurrence_id;
    ELSIF TG_TABLE_NAME = 'finance_cashmovementcorrection' THEN
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_operatingcashmovement
        WHERE organization_id = NEW.organization_id AND id = NEW.cash_movement_id FOR UPDATE;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases FROM public.finance_cashmovementcorrection
        WHERE organization_id = NEW.organization_id AND cash_movement_id = NEW.cash_movement_id;
    ELSE
        SELECT amount, currency INTO target_amount, target_currency
        FROM public.finance_recognitionadjustment
        WHERE organization_id = NEW.organization_id AND id = NEW.recognition_adjustment_id FOR UPDATE;
        SELECT coalesce(sum(amount) FILTER (WHERE direction = 'increase'), 0),
               coalesce(sum(amount) FILTER (WHERE direction = 'decrease'), 0)
        INTO increases, decreases FROM public.finance_recognitionadjustmentcorrection
        WHERE organization_id = NEW.organization_id
          AND recognition_adjustment_id = NEW.recognition_adjustment_id;
    END IF;
    IF target_amount IS NULL OR NEW.currency <> target_currency
       OR (
          target_amount + increases
          + (CASE WHEN NEW.direction = 'increase' THEN NEW.amount ELSE 0 END)
          - decreases
          - (CASE WHEN NEW.direction = 'decrease' THEN NEW.amount ELSE 0 END)
       ) < 0 THEN
        RAISE EXCEPTION 'typed correction is inconsistent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
"""
    + "\n".join(
        f"CREATE TRIGGER {table}_typed_correction_guard BEFORE INSERT ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_typed_correction();"
        for table in (
            "finance_directcostcorrection",
            "finance_expenseoccurrencecorrection",
            "finance_cashmovementcorrection",
            "finance_recognitionadjustmentcorrection",
        )
    )
    + r"""

ALTER TABLE public.finance_recognitionadjustment
ADD CONSTRAINT finance_recognition_reason_ck
CHECK (reason_code IN ('measurement_correction', 'omission_correction', 'duplicate_correction'));

ALTER TABLE public.finance_operatingcashmovement
ADD CONSTRAINT finance_cash_source_kind_ck CHECK (source_kind IN ('direct_cost', 'expense'));

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_cash_source()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE source_amount numeric(18,2); source_currency text; source_organization uuid; original_row record;
BEGIN
    IF NEW.source_kind = 'direct_cost' THEN
        SELECT amount, currency, organization_id INTO source_amount, source_currency, source_organization
        FROM public.finance_actualdirectcost
        WHERE organization_id = NEW.organization_id AND id = NEW.source_id FOR UPDATE;
    ELSE
        SELECT amount, currency, organization_id INTO source_amount, source_currency, source_organization
        FROM public.finance_expenseoccurrence
        WHERE organization_id = NEW.organization_id AND id = NEW.source_id FOR UPDATE;
    END IF;
    IF source_organization IS NULL OR NEW.currency <> source_currency THEN
        RAISE EXCEPTION 'cash source is inconsistent' USING ERRCODE = '23514';
    END IF;
    IF NEW.direction = 'outflow' THEN
        IF (
            SELECT coalesce(sum(CASE direction WHEN 'outflow' THEN amount ELSE -amount END), 0)
            FROM public.finance_operatingcashmovement
            WHERE organization_id = NEW.organization_id
              AND source_kind = NEW.source_kind AND source_id = NEW.source_id
        ) + NEW.amount > source_amount THEN
            RAISE EXCEPTION 'cash outflow exceeds source' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO original_row FROM public.finance_operatingcashmovement
        WHERE organization_id = NEW.organization_id AND id = NEW.original_outflow_id
          AND direction = 'outflow' AND source_kind = NEW.source_kind AND source_id = NEW.source_id
        FOR UPDATE;
        IF original_row.id IS NULL OR (
            SELECT coalesce(sum(amount), 0) FROM public.finance_operatingcashmovement
            WHERE organization_id = NEW.organization_id
              AND original_outflow_id = NEW.original_outflow_id
        ) + NEW.amount > original_row.amount THEN
            RAISE EXCEPTION 'cash recovery exceeds original outflow' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
CREATE TRIGGER finance_cash_source_guard BEFORE INSERT ON public.finance_operatingcashmovement
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_cash_source();
"""
)

GUARD_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS finance_cash_source_guard ON public.finance_operatingcashmovement;
DROP FUNCTION IF EXISTS public.claridez_finance_guard_cash_source();
ALTER TABLE public.finance_operatingcashmovement DROP CONSTRAINT IF EXISTS finance_cash_source_kind_ck;
ALTER TABLE public.finance_recognitionadjustment DROP CONSTRAINT IF EXISTS finance_recognition_reason_ck;
DROP TRIGGER IF EXISTS finance_directcostcorrection_typed_correction_guard ON public.finance_directcostcorrection;
DROP TRIGGER IF EXISTS finance_expenseoccurrencecorrection_typed_correction_guard ON public.finance_expenseoccurrencecorrection;
DROP TRIGGER IF EXISTS finance_cashmovementcorrection_typed_correction_guard ON public.finance_cashmovementcorrection;
DROP TRIGGER IF EXISTS finance_recognitionadjustmentcorrection_typed_correction_guard ON public.finance_recognitionadjustmentcorrection;
DROP FUNCTION IF EXISTS public.claridez_finance_guard_typed_correction();
DROP TRIGGER IF EXISTS finance_allocation_complete ON public.finance_expenseallocation;
DROP TRIGGER IF EXISTS finance_expense_complete ON public.finance_expenseoccurrence;
DROP FUNCTION IF EXISTS public.claridez_finance_expense_deferred_guard();
DROP FUNCTION IF EXISTS public.claridez_finance_check_expense(uuid, uuid);
DROP TRIGGER IF EXISTS finance_plan_line_complete ON public.finance_directcostplanline;
DROP TRIGGER IF EXISTS finance_plan_revision_complete ON public.finance_directcostplanrevision;
DROP FUNCTION IF EXISTS public.claridez_finance_plan_deferred_guard();
DROP FUNCTION IF EXISTS public.claridez_finance_check_plan(uuid, uuid);
DROP TRIGGER IF EXISTS finance_actualdirectcost_open_period_guard ON public.finance_actualdirectcost;
DROP TRIGGER IF EXISTS finance_directcostcorrection_open_period_guard ON public.finance_directcostcorrection;
DROP TRIGGER IF EXISTS finance_expenseoccurrence_open_period_guard ON public.finance_expenseoccurrence;
DROP TRIGGER IF EXISTS finance_expenseoccurrencecorrection_open_period_guard ON public.finance_expenseoccurrencecorrection;
DROP TRIGGER IF EXISTS finance_operatingbudgetrevision_open_period_guard ON public.finance_operatingbudgetrevision;
DROP TRIGGER IF EXISTS finance_operatingcashmovement_open_period_guard ON public.finance_operatingcashmovement;
DROP TRIGGER IF EXISTS finance_cashmovementcorrection_open_period_guard ON public.finance_cashmovementcorrection;
DROP TRIGGER IF EXISTS finance_recognitionadjustment_open_period_guard ON public.finance_recognitionadjustment;
DROP TRIGGER IF EXISTS finance_recognitionadjustmentcorrection_open_period_guard ON public.finance_recognitionadjustmentcorrection;
DROP FUNCTION IF EXISTS public.claridez_finance_guard_open_period();
DROP TRIGGER IF EXISTS finance_recognition_root_venue_guard ON public.finance_recognitionadjustment;
DROP TRIGGER IF EXISTS finance_expcorr_root_venue_guard ON public.finance_expenseoccurrencecorrection;
DROP TRIGGER IF EXISTS finance_alloc_root_venue_guard ON public.finance_expenseallocation;
DROP TRIGGER IF EXISTS finance_cost_root_venue_guard ON public.finance_actualdirectcost;
DROP TRIGGER IF EXISTS finance_evidence_root_venue_guard ON public.finance_operationalcostevidence;
DROP TRIGGER IF EXISTS finance_plan_root_venue_guard ON public.finance_directcostplanrevision;
DROP FUNCTION IF EXISTS public.claridez_finance_guard_root_venue();
DROP FUNCTION IF EXISTS public.claridez_finance_root_has_venue(uuid, uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_recognition_net(uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_recovered_cash(uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_source_cash_net(uuid, text, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_effective_cash(uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_effective_source(uuid, text, uuid);
ALTER TABLE public.finance_operationalperiod DROP CONSTRAINT IF EXISTS finance_period_no_overlap;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0001_initial"),
        ("receivables", "0005_schedule_total_guard"),
        ("scheduling", "0009_allow_terminal_operational_successors"),
    ]

    operations = [
        migrations.RunSQL(_currency_sql(), _currency_reverse_sql()),
        migrations.RunSQL(_tenant_fk_sql(), _tenant_fk_reverse_sql()),
        migrations.RunSQL(GUARD_SQL, GUARD_REVERSE_SQL),
        migrations.RunSQL(IMMUTABILITY_SQL, IMMUTABILITY_REVERSE_SQL),
        migrations.RunSQL(_rls_sql(), _rls_reverse_sql()),
    ]
