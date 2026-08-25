from __future__ import annotations

from importlib import import_module
from typing import cast

from django.db import migrations


def _function_sql(function_name: str) -> str:
    source = import_module(
        "claridez.operations.migrations.0011_p13_projection_guardians"
    ).FORWARD_SQL
    marker = f"CREATE FUNCTION public.{function_name}()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return cast(
        str,
        source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
    )


class Migration(migrations.Migration):
    dependencies = [("operations", "0013_operational_change_impact")]

    operations = [
        migrations.RunSQL(
            "\n".join(
                (
                    _function_sql("claridez_operations_guard_verification_event"),
                    _function_sql("claridez_operations_validate_verification_projection"),
                )
            ),
            migrations.RunSQL.noop,
        )
    ]
