from typing import Any

from django.db import migrations, models


def require_empty_p13_history(apps: Any, schema_editor: Any) -> None:
    evidence = apps.get_model("operations", "OperationalEvidence")
    if evidence.objects.exists():
        raise RuntimeError(
            "P13 evidence exists without request hash; refuse to invent idempotency history."
        )


class Migration(migrations.Migration):
    dependencies = [("operations", "0014_refresh_verification_guardians")]

    operations = [
        migrations.AddField(
            model_name="operationalevidence",
            name="payload_sha256",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.RunPython(require_empty_p13_history, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="operationalevidence",
            name="payload_sha256",
            field=models.CharField(max_length=64),
        ),
    ]
