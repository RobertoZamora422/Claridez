"""Crear las tablas sintéticas de comparación."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TechnicalOrganization",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True),
                ),
                ("label", models.CharField(max_length=40)),
            ],
            options={"db_table": "claridez_spike_organization"},
        ),
        migrations.CreateModel(
            name="ApplicationTechnicalRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True),
                ),
                ("organization_id", models.UUIDField()),
                ("external_key", models.CharField(max_length=80)),
                ("payload", models.CharField(max_length=120)),
            ],
            options={
                "db_table": "claridez_spike_app_record",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization_id", "id"), name="spike_app_record_org_id_uniq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization_id", "external_key"),
                        name="spike_app_record_org_key_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ApplicationTechnicalChildRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True),
                ),
                ("organization_id", models.UUIDField()),
                ("external_key", models.CharField(max_length=80)),
                ("payload", models.CharField(max_length=120)),
                ("parent_id", models.UUIDField()),
            ],
            options={
                "db_table": "claridez_spike_app_child",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization_id", "external_key"),
                        name="spike_app_child_org_key_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RlsTechnicalRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True),
                ),
                ("organization_id", models.UUIDField()),
                ("external_key", models.CharField(max_length=80)),
                ("payload", models.CharField(max_length=120)),
            ],
            options={
                "db_table": "claridez_spike_rls_record",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization_id", "id"), name="spike_rls_record_org_id_uniq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization_id", "external_key"),
                        name="spike_rls_record_org_key_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RlsTechnicalChildRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True),
                ),
                ("organization_id", models.UUIDField()),
                ("external_key", models.CharField(max_length=80)),
                ("payload", models.CharField(max_length=120)),
                ("parent_id", models.UUIDField()),
            ],
            options={
                "db_table": "claridez_spike_rls_child",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization_id", "external_key"),
                        name="spike_rls_child_org_key_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RlsDefaultDenyRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True),
                ),
                ("organization_id", models.UUIDField()),
                ("external_key", models.CharField(max_length=80)),
                ("payload", models.CharField(max_length=120)),
            ],
            options={"db_table": "claridez_spike_rls_default_deny"},
        ),
    ]
