from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0007_remove_reservation_cancelled_by_membership_and_more"),
        ("operations", "0003_alter_eventpreparation_reservation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="Reservation")],
        ),
    ]
