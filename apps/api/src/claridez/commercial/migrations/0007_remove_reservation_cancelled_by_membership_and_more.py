from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0006_repair_cutover_history"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="reservation", name="cancelled_by_membership"),
                migrations.RemoveField(model_name="reservation", name="confirmed_by_membership"),
                migrations.RemoveField(model_name="reservation", name="event_request"),
                migrations.RemoveField(model_name="reservation", name="organization"),
                migrations.RemoveField(model_name="reservation", name="quotation_version"),
                migrations.RemoveField(model_name="reservation", name="space"),
                migrations.RemoveField(
                    model_name="reservation", name="waiver_authorized_by_membership"
                ),
            ],
        ),
    ]
