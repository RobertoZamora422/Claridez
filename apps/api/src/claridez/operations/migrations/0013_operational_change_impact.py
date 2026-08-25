from typing import Any

from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Trim


def require_empty_p13_history(apps: Any, schema_editor: Any) -> None:
    proposal = apps.get_model("operations", "OperationalChangeProposal")
    if proposal.objects.exists():
        raise RuntimeError(
            "P13 change proposals exist without impact; refuse to invent historical impact."
        )


class Migration(migrations.Migration):
    dependencies = [("operations", "0012_refresh_post_close_guardian")]

    operations = [
        migrations.AddField(
            model_name="operationalchangeproposal",
            name="impact",
            field=models.CharField(max_length=1000, null=True),
        ),
        migrations.RunPython(require_empty_p13_history, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="operationalchangeproposal",
            name="impact",
            field=models.CharField(max_length=1000),
        ),
        migrations.AddConstraint(
            model_name="operationalchangeproposal",
            constraint=models.CheckConstraint(
                condition=Q(impact=Trim("impact")) & ~Q(impact=""),
                name="operations_change_proposal_impact_ck",
            ),
        ),
    ]
