from __future__ import annotations

from importlib import import_module
from typing import cast

from django.db import migrations


def _function_sql(function_name: str) -> str:
    source = import_module("claridez.operations.migrations.0006_p13_integrity").GUARDIAN_SQL
    marker = f"CREATE FUNCTION public.{function_name}()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return cast(
        str,
        source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
    )


REFRESH_SQL = "\n".join(
    (
        _function_sql("claridez_operations_guard_phase_fact"),
        _function_sql("claridez_operations_guard_window"),
    )
)


class Migration(migrations.Migration):
    dependencies = [("operations", "0007_operationcommand_actor")]

    operations = [migrations.RunSQL(REFRESH_SQL, migrations.RunSQL.noop)]
