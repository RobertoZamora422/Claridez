from __future__ import annotations

from pathlib import Path

from django.db import migrations


def _function_sql(filename: str, function_name: str) -> str:
    source = (Path(__file__).parent / filename).read_text(encoding="utf-8")
    marker = f"CREATE FUNCTION public.{function_name}()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


FORWARD_SQL = "\n".join(
    (
        _function_sql("0006_p13_integrity.py", "claridez_operations_validate_phase_timeline"),
        _function_sql(
            "0011_p13_projection_guardians.py",
            "claridez_operations_validate_verification_projection",
        ),
        _function_sql(
            "0011_p13_projection_guardians.py",
            "claridez_operations_validate_incident_projection",
        ),
        _function_sql(
            "0011_p13_projection_guardians.py",
            "claridez_operations_guard_change_projection",
        ),
    )
)


class Migration(migrations.Migration):
    dependencies = [("operations", "0015_operational_evidence_payload_hash")]

    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
