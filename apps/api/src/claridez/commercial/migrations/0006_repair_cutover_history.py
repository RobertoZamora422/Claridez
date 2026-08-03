from django.db import migrations


def backfill_missing_cutover_state(apps, schema_editor):  # type: ignore[no-untyped-def]
    EventRequest = apps.get_model("commercial", "EventRequest")
    EventRequestHistory = apps.get_model("commercial", "EventRequestHistory")
    Organization = apps.get_model("organizations", "Organization")
    alias = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        previous = cursor.fetchone()[0] or ""
        try:
            for organization_id in Organization.objects.using(alias).values_list("id", flat=True):
                cursor.execute(
                    "SELECT set_config('claridez.organization_id', %s, true)",
                    [str(organization_id)],
                )
                recorded_ids = (
                    EventRequestHistory.objects.using(alias)
                    .filter(organization_id=organization_id)
                    .values_list("event_request_id", flat=True)
                )
                rows = (
                    EventRequest.objects.using(alias)
                    .filter(organization_id=organization_id)
                    .exclude(pk__in=recorded_ids)
                    .order_by("id")
                    .iterator(chunk_size=500)
                )
                EventRequestHistory.objects.using(alias).bulk_create(
                    [
                        EventRequestHistory(
                            organization_id=row.organization_id,
                            event_request_id=row.pk,
                            kind="cutover_state",
                            status=row.status,
                            request_revision=row.revision,
                            origin=row.origin,
                            origin_detail=row.origin_detail,
                            responsible_membership_id=row.responsible_membership_id,
                            actor_membership_id=None,
                            occurred_at=None,
                            provenance="cutover_snapshot",
                            reason=row.closed_reason,
                        )
                        for row in rows
                    ],
                    batch_size=500,
                )
        finally:
            cursor.execute("SELECT set_config('claridez.organization_id', %s, true)", [previous])


class Migration(migrations.Migration):
    dependencies = [("commercial", "0005_people_state_and_event_history")]

    operations = [migrations.RunPython(backfill_missing_cutover_state, migrations.RunPython.noop)]
