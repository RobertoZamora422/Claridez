from __future__ import annotations

from importlib import import_module
from typing import cast

from django.db import migrations


def _guardian_sql(function_name: str) -> str:
    source = import_module("claridez.operations.migrations.0006_p13_integrity").GUARDIAN_SQL
    marker = f"CREATE FUNCTION public.{function_name}()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return cast(
        str,
        source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
    )


class Migration(migrations.Migration):
    dependencies = [("operations", "0011_p13_projection_guardians")]

    operations = [
        migrations.RunSQL(
            "\n".join(
                (
                    _guardian_sql("claridez_operations_guard_phase_fact"),
                    _guardian_sql("claridez_operations_guard_post_close"),
                )
            ),
            migrations.RunSQL.noop,
        )
    ]
