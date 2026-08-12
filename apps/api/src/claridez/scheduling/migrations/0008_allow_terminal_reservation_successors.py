from __future__ import annotations

import re

from django.db import migrations

FUNCTION_SIGNATURE = "public.claridez_validate_scheduling_integrity()"
TERMINAL_REJECTION = r"\n\s+OR successor\.status NOT IN \('provisional', 'confirmed'\)"
QUOTATION_CHECK = (
    r"(?P<indent>\s+)OR successor\.quotation_version_id <> predecessor\.quotation_version_id"
)


def allow_terminal_successors(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT pg_get_functiondef(%s::regprocedure)", [FUNCTION_SIGNATURE])
        definition = cursor.fetchone()[0]
        patched, count = re.subn(TERMINAL_REJECTION, "", definition, count=1)
        if count != 1:
            raise RuntimeError("The scheduling integrity guardian could not be upgraded.")
        cursor.execute(patched)


def reject_terminal_successors(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT pg_get_functiondef(%s::regprocedure)", [FUNCTION_SIGNATURE])
        definition = cursor.fetchone()[0]
        match = re.search(QUOTATION_CHECK, definition)
        if match is None:
            raise RuntimeError("The scheduling integrity guardian could not be downgraded.")
        check = match.group(0)
        indent = match.group("indent")
        replacement = check + indent + "OR successor.status NOT IN ('provisional', 'confirmed')"
        patched = definition[: match.start()] + replacement + definition[match.end() :]
        cursor.execute(patched)


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0007_schedule_event_shape_guard")]

    operations = [
        migrations.RunPython(allow_terminal_successors, reject_terminal_successors),
    ]
