# ruff: noqa: E501

from django.db import migrations

FORWARD_SQL = r"""
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
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("finance", "0002_integrity_rls_and_guardians")]

    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
