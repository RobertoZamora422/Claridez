import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0002_commercial_operations_guardian"),
        ("scheduling", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="eventpreparation",
                    name="reservation",
                    field=models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        related_name="preparation",
                        serialize=False,
                        to="scheduling.reservation",
                    ),
                )
            ],
        ),
    ]
