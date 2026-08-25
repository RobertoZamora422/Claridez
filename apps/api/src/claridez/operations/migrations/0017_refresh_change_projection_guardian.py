from __future__ import annotations

from pathlib import Path

from django.db import migrations


def _function_sql(function_name: str) -> str:
    source = (Path(__file__).parent / "0011_p13_projection_guardians.py").read_text(
        encoding="utf-8"
    )
    marker = f"CREATE FUNCTION public.{function_name}()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


class Migration(migrations.Migration):
    dependencies = [("operations", "0016_deferred_guardian_tenant_context")]

    operations = [
        migrations.RunSQL(
            _function_sql("claridez_operations_guard_change_projection"),
            migrations.RunSQL.noop,
        )
    ]
