from __future__ import annotations

from importlib import import_module
from typing import cast

from django.db import migrations


def _allocation_guardian_sql() -> str:
    source = import_module("claridez.resources.migrations.0004_p13_temporal_provenance").FORWARD_SQL
    marker = "CREATE OR REPLACE FUNCTION public.claridez_resources_guard_allocation()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return cast(str, source[start:end])


class Migration(migrations.Migration):
    dependencies = [("resources", "0005_refresh_p13_allocation_guardian")]

    operations = [migrations.RunSQL(_allocation_guardian_sql(), migrations.RunSQL.noop)]
