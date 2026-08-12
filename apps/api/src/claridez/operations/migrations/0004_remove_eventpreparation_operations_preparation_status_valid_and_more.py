import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0003_alter_eventpreparation_reservation"),
        ("organizations", "0004_venues_and_spaces"),
        ("scheduling", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="eventpreparation",
            name="operations_preparation_status_valid",
        ),
        migrations.AddField(
            model_name="eventpreparation",
            name="rescheduled_to_reservation",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rescheduled_from_preparation",
                to="scheduling.reservation",
            ),
        ),
        migrations.AddField(
            model_name="preparationitem",
            name="carried_from_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="carried_copies",
                to="operations.preparationitem",
            ),
        ),
        migrations.AlterField(
            model_name="eventpreparation",
            name="status",
            field=models.CharField(
                choices=[
                    ("preparing", "En preparación"),
                    ("ready", "Listo"),
                    ("in_progress", "En ejecución"),
                    ("completed", "Completado"),
                    ("cancelled", "Cancelado"),
                    ("rescheduled", "Reprogramado"),
                ],
                default="preparing",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="preparationtransition",
            name="cause",
            field=models.CharField(
                choices=[
                    ("initialized", "Inicializada"),
                    ("readiness_declared", "Lista"),
                    ("checklist_reopened", "Checklist reabierto"),
                    ("execution_started", "Ejecución iniciada"),
                    ("execution_completed", "Ejecución completada"),
                    ("commercial_cancellation", "Cancelación comercial"),
                    ("schedule_reschedule", "Reprogramación de agenda"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="preparationtransition",
            name="to_status",
            field=models.CharField(
                choices=[
                    ("preparing", "En preparación"),
                    ("ready", "Listo"),
                    ("in_progress", "En ejecución"),
                    ("completed", "Completado"),
                    ("cancelled", "Cancelado"),
                    ("rescheduled", "Reprogramado"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="eventpreparation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "status__in",
                        [
                            "preparing",
                            "ready",
                            "in_progress",
                            "completed",
                            "cancelled",
                            "rescheduled",
                        ],
                    )
                ),
                name="operations_preparation_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="eventpreparation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("rescheduled_to_reservation__isnull", False), ("status", "rescheduled")
                    ),
                    models.Q(
                        models.Q(("status", "rescheduled"), _negated=True),
                        ("rescheduled_to_reservation__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="operations_preparation_rescheduled_evidence",
            ),
        ),
        migrations.AddConstraint(
            model_name="preparationitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("carried_from_item__isnull", False)),
                fields=("organization", "preparation", "carried_from_item"),
                name="operations_item_org_carried_uq",
            ),
        ),
    ]
