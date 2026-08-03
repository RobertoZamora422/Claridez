# ruff: noqa: E501

import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("commercial", "0004_multi_space_and_catalog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Person",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("full_name", models.CharField(max_length=150)),
                        ("phone_e164", models.CharField(max_length=13)),
                        ("email", models.EmailField(blank=True, max_length=254)),
                        (
                            "origin",
                            models.CharField(
                                choices=[
                                    ("whatsapp", "WhatsApp"),
                                    ("phone_call", "Llamada"),
                                    ("social_network", "Red social"),
                                    ("referral", "Referido"),
                                    ("walk_in", "Visita"),
                                    ("website", "Sitio web"),
                                    ("other", "Otro"),
                                ],
                                max_length=24,
                            ),
                        ),
                        ("origin_detail", models.CharField(blank=True, max_length=160)),
                        ("revision", models.PositiveIntegerField(default=1)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "organization",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="organizations.organization",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "commercial_person",
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("organization", "id"),
                                name="commercial_person_org_id_uq",
                            ),
                            models.UniqueConstraint(
                                fields=("organization", "phone_e164"),
                                name="commercial_person_org_phone_uq",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(
                                    (
                                        "full_name",
                                        django.db.models.functions.text.Trim("full_name"),
                                    ),
                                    models.Q(("full_name", ""), _negated=True),
                                ),
                                name="commercial_person_name_canonical",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(
                                    ("phone_e164__regex", r"^\+593(?:[2-7][0-9]{7}|9[0-9]{8})$")
                                ),
                                name="commercial_person_phone_ec",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(
                                    (
                                        "origin__in",
                                        [
                                            "whatsapp",
                                            "phone_call",
                                            "social_network",
                                            "referral",
                                            "walk_in",
                                            "website",
                                            "other",
                                        ],
                                    )
                                ),
                                name="commercial_person_origin_valid",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(("revision__gte", 1)),
                                name="commercial_person_revision_positive",
                            ),
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="PersonRevision",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("revision", models.PositiveIntegerField()),
                        ("full_name", models.CharField(max_length=150)),
                        ("phone_e164", models.CharField(max_length=13)),
                        ("email", models.EmailField(blank=True, max_length=254)),
                        (
                            "origin",
                            models.CharField(
                                choices=[
                                    ("whatsapp", "WhatsApp"),
                                    ("phone_call", "Llamada"),
                                    ("social_network", "Red social"),
                                    ("referral", "Referido"),
                                    ("walk_in", "Visita"),
                                    ("website", "Sitio web"),
                                    ("other", "Otro"),
                                ],
                                max_length=24,
                            ),
                        ),
                        ("origin_detail", models.CharField(blank=True, max_length=160)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "changed_by",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "organization",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="organizations.organization",
                            ),
                        ),
                        (
                            "person",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="revisions",
                                to="people.person",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "commercial_personrevision",
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("organization", "id"),
                                name="commercial_personrevision_org_id_uq",
                            ),
                            models.UniqueConstraint(
                                fields=("organization", "person", "revision"),
                                name="commercial_personrevision_org_person_rev_uq",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(("revision__gte", 1)),
                                name="commercial_personrevision_revision_positive",
                            ),
                        ],
                    },
                ),
            ],
        )
    ]
