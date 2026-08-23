# ruff: noqa: E501

from django.db import migrations, models

FORWARD_SQL = r"""
DO $block$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.finance_operatingcashmovement
        WHERE source_kind = 'expense'
    ) THEN
        RAISE EXCEPTION
            'existing expense cash requires an explicit corrective migration before P11 cutover';
    END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_plan_baseline()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    preparation_id uuid;
    execution_started_at timestamptz;
    expected_revision integer;
BEGIN
    SELECT preparation.reservation_id, preparation.started_at
    INTO preparation_id, execution_started_at
    FROM public.operations_eventpreparation preparation
    JOIN public.commercial_reservation reservation
      ON reservation.organization_id = preparation.organization_id
     AND reservation.id = preparation.reservation_id
    WHERE preparation.organization_id = NEW.organization_id
      AND reservation.root_id = NEW.root_reservation_id
    ORDER BY reservation.created_at DESC, reservation.id DESC
    LIMIT 1
    FOR UPDATE OF preparation;

    IF preparation_id IS NULL THEN
        RAISE EXCEPTION 'direct cost plan requires operational preparation'
        USING ERRCODE = '23514';
    END IF;
    IF execution_started_at IS NOT NULL THEN
        RAISE EXCEPTION 'direct cost baseline is already frozen'
        USING ERRCODE = '23514';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':plan:' || NEW.root_reservation_id::text,
        0
    ));
    SELECT coalesce(max(revision), 0) + 1
    INTO expected_revision
    FROM public.finance_directcostplanrevision
    WHERE organization_id = NEW.organization_id
      AND root_reservation_id = NEW.root_reservation_id;
    IF NEW.revision <> expected_revision THEN
        RAISE EXCEPTION 'direct cost plan revision is not the next serialized revision'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_valid_attributions(
    payload jsonb, expected_amount numeric
) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public AS $function$
    SELECT jsonb_typeof(payload) = 'array'
       AND jsonb_array_length(payload) > 0
       AND coalesce(bool_and(
            item.amount > 0
            AND (
                (item.scope = 'business'
                 AND item.root_reservation_id IS NULL AND item.venue_id IS NULL)
                OR (item.scope = 'venue'
                    AND item.root_reservation_id IS NULL AND item.venue_id IS NOT NULL)
                OR (item.scope = 'event'
                    AND item.root_reservation_id IS NOT NULL AND item.venue_id IS NOT NULL)
            )
       ), false)
       AND count(*) = count(DISTINCT (
            item.scope, item.root_reservation_id, item.venue_id
       ))
       AND coalesce(sum(item.amount), 0) = expected_amount
    FROM jsonb_to_recordset(payload) AS item(
        scope text,
        root_reservation_id uuid,
        venue_id uuid,
        amount numeric
    );
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_attribution_amount(
    payload jsonb, target_scope text, target_root uuid, target_venue uuid
) RETURNS numeric
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce(sum(item.amount), 0)
    FROM jsonb_to_recordset(payload) AS item(
        scope text,
        root_reservation_id uuid,
        venue_id uuid,
        amount numeric
    )
    WHERE item.scope = target_scope
      AND item.root_reservation_id IS NOT DISTINCT FROM target_root
      AND item.venue_id IS NOT DISTINCT FROM target_venue;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_expense_scope_capacity(
    target_organization uuid,
    target_expense uuid,
    target_scope text,
    target_root uuid,
    target_venue uuid
) RETURNS numeric
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce((
        SELECT sum(allocation.amount)
        FROM public.finance_expenseallocation allocation
        WHERE allocation.organization_id = target_organization
          AND allocation.expense_occurrence_id = target_expense
          AND allocation.scope = target_scope
          AND allocation.root_reservation_id IS NOT DISTINCT FROM target_root
          AND allocation.venue_id IS NOT DISTINCT FROM target_venue
    ), 0) + coalesce((
        SELECT sum(CASE correction.direction
            WHEN 'increase' THEN correction.amount ELSE -correction.amount END)
        FROM public.finance_expenseoccurrencecorrection correction
        WHERE correction.organization_id = target_organization
          AND correction.expense_occurrence_id = target_expense
          AND correction.scope = target_scope
          AND correction.root_reservation_id IS NOT DISTINCT FROM target_root
          AND correction.venue_id IS NOT DISTINCT FROM target_venue
    ), 0);
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_movement_scope_effective(
    target_organization uuid,
    target_movement uuid,
    target_scope text,
    target_root uuid,
    target_venue uuid
) RETURNS numeric
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT public.claridez_finance_attribution_amount(
               movement.expense_attributions, target_scope, target_root, target_venue
           )
         + coalesce(sum(
               CASE correction.direction WHEN 'increase' THEN 1 ELSE -1 END
               * public.claridez_finance_attribution_amount(
                   correction.expense_attributions, target_scope, target_root, target_venue
               )
           ), 0)
    FROM public.finance_operatingcashmovement movement
    LEFT JOIN public.finance_cashmovementcorrection correction
      ON correction.organization_id = movement.organization_id
     AND correction.cash_movement_id = movement.id
    WHERE movement.organization_id = target_organization
      AND movement.id = target_movement
    GROUP BY movement.id;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_recovered_scope(
    target_organization uuid,
    target_outflow uuid,
    target_scope text,
    target_root uuid,
    target_venue uuid
) RETURNS numeric
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce(sum(public.claridez_finance_movement_scope_effective(
        movement.organization_id,
        movement.id,
        target_scope,
        target_root,
        target_venue
    )), 0)
    FROM public.finance_operatingcashmovement movement
    WHERE movement.organization_id = target_organization
      AND movement.original_outflow_id = target_outflow
      AND movement.direction = 'recovery';
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_expense_scope_cash_net(
    target_organization uuid,
    target_expense uuid,
    target_scope text,
    target_root uuid,
    target_venue uuid
) RETURNS numeric
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $function$
    SELECT coalesce(sum(
        CASE movement.direction WHEN 'outflow' THEN 1 ELSE -1 END
        * public.claridez_finance_movement_scope_effective(
            movement.organization_id,
            movement.id,
            target_scope,
            target_root,
            target_venue
        )
    ), 0)
    FROM public.finance_operatingcashmovement movement
    WHERE movement.organization_id = target_organization
      AND movement.source_kind = 'expense'
      AND movement.source_id = target_expense;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_cash_attributions()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    item record;
    capacity numeric;
BEGIN
    IF NEW.source_kind <> 'expense' THEN
        IF NEW.expense_attributions <> '[]'::jsonb THEN
            RAISE EXCEPTION 'direct cost cash cannot carry expense attributions'
            USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':cash:expense:' || NEW.source_id::text,
        0
    ));
    IF NOT public.claridez_finance_valid_attributions(
        NEW.expense_attributions, NEW.amount
    ) THEN
        RAISE EXCEPTION 'expense cash attributions do not match movement'
        USING ERRCODE = '23514';
    END IF;
    FOR item IN
        SELECT * FROM jsonb_to_recordset(NEW.expense_attributions) AS value(
            scope text, root_reservation_id uuid, venue_id uuid, amount numeric
        )
    LOOP
        capacity := public.claridez_finance_expense_scope_capacity(
            NEW.organization_id,
            NEW.source_id,
            item.scope,
            item.root_reservation_id,
            item.venue_id
        );
        IF capacity <= 0 OR (
            NEW.direction = 'outflow'
            AND public.claridez_finance_expense_scope_cash_net(
                NEW.organization_id,
                NEW.source_id,
                item.scope,
                item.root_reservation_id,
                item.venue_id
            ) + item.amount > capacity
        ) THEN
            RAISE EXCEPTION 'expense cash exceeds explicit allocation'
            USING ERRCODE = '23514';
        END IF;
        IF NEW.direction = 'recovery' AND (
            public.claridez_finance_recovered_scope(
                NEW.organization_id,
                NEW.original_outflow_id,
                item.scope,
                item.root_reservation_id,
                item.venue_id
            ) + item.amount
            > coalesce(public.claridez_finance_movement_scope_effective(
                NEW.organization_id,
                NEW.original_outflow_id,
                item.scope,
                item.root_reservation_id,
                item.venue_id
            ), 0)
        ) THEN
            RAISE EXCEPTION 'cash recovery exceeds original attribution'
            USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_cash_correction_attributions()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    movement record;
    item record;
    effect numeric;
    current_amount numeric;
BEGIN
    SELECT source_kind, source_id, direction, original_outflow_id, expense_attributions
    INTO movement
    FROM public.finance_operatingcashmovement
    WHERE organization_id = NEW.organization_id
      AND id = NEW.cash_movement_id;
    IF movement.source_kind <> 'expense' THEN
        IF NEW.expense_attributions <> '[]'::jsonb THEN
            RAISE EXCEPTION 'direct cost cash correction cannot carry expense attributions'
            USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':cash:expense:' || movement.source_id::text,
        0
    ));
    IF NOT public.claridez_finance_valid_attributions(
        NEW.expense_attributions, NEW.amount
    ) THEN
        RAISE EXCEPTION 'expense cash correction attributions do not match correction'
        USING ERRCODE = '23514';
    END IF;
    effect := CASE NEW.direction WHEN 'increase' THEN 1 ELSE -1 END;
    FOR item IN
        SELECT * FROM jsonb_to_recordset(NEW.expense_attributions) AS value(
            scope text, root_reservation_id uuid, venue_id uuid, amount numeric
        )
    LOOP
        IF public.claridez_finance_attribution_amount(
            movement.expense_attributions,
            item.scope,
            item.root_reservation_id,
            item.venue_id
        ) <= 0 THEN
            RAISE EXCEPTION 'cash correction attribution is not in original movement'
            USING ERRCODE = '23514';
        END IF;
        current_amount := public.claridez_finance_movement_scope_effective(
            NEW.organization_id,
            NEW.cash_movement_id,
            item.scope,
            item.root_reservation_id,
            item.venue_id
        );
        IF current_amount + effect * item.amount < 0 THEN
            RAISE EXCEPTION 'cash correction makes attribution negative'
            USING ERRCODE = '23514';
        END IF;
        IF movement.direction = 'outflow' THEN
            IF public.claridez_finance_expense_scope_cash_net(
                NEW.organization_id,
                movement.source_id,
                item.scope,
                item.root_reservation_id,
                item.venue_id
            ) + effect * item.amount
            > public.claridez_finance_expense_scope_capacity(
                NEW.organization_id,
                movement.source_id,
                item.scope,
                item.root_reservation_id,
                item.venue_id
            ) OR public.claridez_finance_recovered_scope(
                NEW.organization_id,
                NEW.cash_movement_id,
                item.scope,
                item.root_reservation_id,
                item.venue_id
            ) > current_amount + effect * item.amount THEN
                RAISE EXCEPTION 'cash correction breaks expense allocation'
                USING ERRCODE = '23514';
            END IF;
        ELSIF public.claridez_finance_recovered_scope(
            NEW.organization_id,
            movement.original_outflow_id,
            item.scope,
            item.root_reservation_id,
            item.venue_id
        ) + effect * item.amount
        > coalesce(public.claridez_finance_movement_scope_effective(
            NEW.organization_id,
            movement.original_outflow_id,
            item.scope,
            item.root_reservation_id,
            item.venue_id
        ), 0) THEN
            RAISE EXCEPTION 'cash recovery correction exceeds original attribution'
            USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_finance_guard_expense_correction_scope_cash()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE
    corrected_capacity numeric;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'finance:' || NEW.organization_id::text || ':cash:expense:'
        || NEW.expense_occurrence_id::text,
        0
    ));
    corrected_capacity := public.claridez_finance_expense_scope_capacity(
        NEW.organization_id,
        NEW.expense_occurrence_id,
        NEW.scope,
        NEW.root_reservation_id,
        NEW.venue_id
    ) + CASE NEW.direction WHEN 'increase' THEN NEW.amount ELSE -NEW.amount END;
    IF corrected_capacity < 0 OR corrected_capacity
       < public.claridez_finance_expense_scope_cash_net(
            NEW.organization_id,
            NEW.expense_occurrence_id,
            NEW.scope,
            NEW.root_reservation_id,
            NEW.venue_id
       ) THEN
        RAISE EXCEPTION 'expense correction leaves cash above explicit allocation'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION public.claridez_finance_guard_plan_baseline(),
    public.claridez_finance_valid_attributions(jsonb, numeric),
    public.claridez_finance_attribution_amount(jsonb, text, uuid, uuid),
    public.claridez_finance_expense_scope_capacity(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_movement_scope_effective(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_recovered_scope(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_expense_scope_cash_net(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_guard_cash_attributions(),
    public.claridez_finance_guard_cash_correction_attributions(),
    public.claridez_finance_guard_expense_correction_scope_cash()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_finance_guard_plan_baseline(),
    public.claridez_finance_valid_attributions(jsonb, numeric),
    public.claridez_finance_attribution_amount(jsonb, text, uuid, uuid),
    public.claridez_finance_expense_scope_capacity(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_movement_scope_effective(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_recovered_scope(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_expense_scope_cash_net(uuid, uuid, text, uuid, uuid),
    public.claridez_finance_guard_cash_attributions(),
    public.claridez_finance_guard_cash_correction_attributions(),
    public.claridez_finance_guard_expense_correction_scope_cash()
TO claridez_app, claridez_test_runner, claridez_migrator;

CREATE TRIGGER finance_plan_baseline_freeze_guard
BEFORE INSERT ON public.finance_directcostplanrevision
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_plan_baseline();
CREATE TRIGGER finance_cash_attribution_guard
BEFORE INSERT ON public.finance_operatingcashmovement
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_cash_attributions();
CREATE TRIGGER finance_cashmovementcorrection_attribution_guard
BEFORE INSERT ON public.finance_cashmovementcorrection
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_cash_correction_attributions();
CREATE TRIGGER finance_expenseoccurrencecorrection_allocation_cash_guard
BEFORE INSERT ON public.finance_expenseoccurrencecorrection
FOR EACH ROW EXECUTE FUNCTION public.claridez_finance_guard_expense_correction_scope_cash();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS finance_expenseoccurrencecorrection_allocation_cash_guard
ON public.finance_expenseoccurrencecorrection;
DROP TRIGGER IF EXISTS finance_cashmovementcorrection_attribution_guard
ON public.finance_cashmovementcorrection;
DROP TRIGGER IF EXISTS finance_cash_attribution_guard
ON public.finance_operatingcashmovement;
DROP TRIGGER IF EXISTS finance_plan_baseline_freeze_guard
ON public.finance_directcostplanrevision;

DROP FUNCTION IF EXISTS public.claridez_finance_guard_expense_correction_scope_cash();
DROP FUNCTION IF EXISTS public.claridez_finance_guard_cash_correction_attributions();
DROP FUNCTION IF EXISTS public.claridez_finance_guard_cash_attributions();
DROP FUNCTION IF EXISTS public.claridez_finance_expense_scope_cash_net(uuid, uuid, text, uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_recovered_scope(uuid, uuid, text, uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_movement_scope_effective(uuid, uuid, text, uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_expense_scope_capacity(uuid, uuid, text, uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_attribution_amount(jsonb, text, uuid, uuid);
DROP FUNCTION IF EXISTS public.claridez_finance_valid_attributions(jsonb, numeric);
DROP FUNCTION IF EXISTS public.claridez_finance_guard_plan_baseline();
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("finance", "0004_cash_invariant_hardening")]

    operations = [
        migrations.AddField(
            model_name="operatingcashmovement",
            name="expense_attributions",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="cashmovementcorrection",
            name="expense_attributions",
            field=models.JSONField(default=list),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
