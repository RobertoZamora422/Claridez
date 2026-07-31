"""Integridad compuesta mediante ORM, bulk y SQL directo."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.db import DatabaseError, IntegrityError, connections, transaction

from spikes.tenancy.context import ValidatedTechnicalOrganization, tenant_scope
from spikes.tenancy.models import (
    ApplicationTechnicalChildRecord,
    ApplicationTechnicalRecord,
    RlsTechnicalChildRecord,
)
from spikes.tenancy.tests.conftest import (
    APP_RECORD_A,
    APP_RECORD_B,
    RLS_RECORD_A,
    RLS_RECORD_B,
    EvidenceRecorder,
    Organizations,
)

pytestmark = pytest.mark.tenancy_spike


@pytest.mark.parametrize(
    ("child_model", "foreign_parent"),
    [
        (ApplicationTechnicalChildRecord, APP_RECORD_B),
        (RlsTechnicalChildRecord, RLS_RECORD_B),
    ],
)
def test_orm_rejects_cross_tenant_parent(
    child_model: Any, foreign_parent: uuid.UUID, synthetic_rows: Organizations
) -> None:
    with (
        tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)),
        pytest.raises((IntegrityError, DatabaseError)),
        transaction.atomic(),
    ):
        child_model.spike_unfiltered_objects.create(
            organization_id=synthetic_rows.a,
            parent_id=foreign_parent,
            external_key="cross-orm",
            payload="synthetic",
        )


def test_bulk_and_direct_sql_reject_cross_tenant_parent(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        with pytest.raises(IntegrityError), transaction.atomic():
            ApplicationTechnicalChildRecord.spike_unfiltered_objects.bulk_create(
                [
                    ApplicationTechnicalChildRecord(
                        organization_id=synthetic_rows.a,
                        parent_id=APP_RECORD_B,
                        external_key="cross-bulk",
                        payload="synthetic",
                    )
                ]
            )
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connections["default"].cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO claridez_spike_rls_child "
                "(id, organization_id, parent_id, external_key, payload) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    uuid.uuid4(),
                    synthetic_rows.a,
                    RLS_RECORD_B,
                    "cross-sql",
                    "synthetic",
                ),
            )
    evidence.record("composite_fk_orm", "rejected")
    evidence.record("composite_fk_bulk", "rejected")
    evidence.record("composite_fk_direct_sql", "rejected")


def test_valid_relation_and_join_are_tenant_aware(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        ApplicationTechnicalChildRecord.spike_unfiltered_objects.create(
            organization_id=synthetic_rows.a,
            parent_id=APP_RECORD_A,
            external_key="valid-child",
            payload="synthetic",
        )
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM claridez_spike_app_child child
                JOIN claridez_spike_app_record parent
                  ON parent.organization_id = child.organization_id
                 AND parent.id = child.parent_id
                WHERE child.organization_id = %s
                """,
                (synthetic_rows.a,),
            )
            assert cursor.fetchone()[0] == 1
        RlsTechnicalChildRecord.spike_unfiltered_objects.create(
            organization_id=synthetic_rows.a,
            parent_id=RLS_RECORD_A,
            external_key="valid-rls-child",
            payload="synthetic",
        )
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM claridez_spike_rls_child child
                JOIN claridez_spike_rls_record parent
                  ON parent.organization_id = child.organization_id
                 AND parent.id = child.parent_id
                """
            )
            assert cursor.fetchone()[0] == 1
    evidence.record("tenant_aware_join", "valid_relation_visible")
    evidence.record("rls_tenant_aware_join", "isolated")


def test_uniqueness_is_scoped_by_organization(synthetic_rows: Organizations) -> None:
    with connections["test_runner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO claridez_spike_app_record "
            "(id, organization_id, external_key, payload) VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), synthetic_rows.a, "shared-key", "synthetic"),
        )
        cursor.execute(
            "INSERT INTO claridez_spike_app_record "
            "(id, organization_id, external_key, payload) VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), synthetic_rows.b, "shared-key", "synthetic"),
        )
        with pytest.raises(IntegrityError), transaction.atomic(using="test_runner"):
            cursor.execute(
                "INSERT INTO claridez_spike_app_record "
                "(id, organization_id, external_key, payload) VALUES (%s, %s, %s, %s)",
                (uuid.uuid4(), synthetic_rows.a, "shared-key", "synthetic"),
            )


def test_column_privileges_make_normal_save_fragile(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        record = ApplicationTechnicalRecord.objects.get(id=APP_RECORD_A)
        record.payload = "normal-save"
        with pytest.raises(DatabaseError), transaction.atomic():
            record.save()
        record.payload = "explicit-fields"
        record.save(update_fields=["payload"])
        assert ApplicationTechnicalRecord.objects.get(id=APP_RECORD_A).payload == "explicit-fields"
        with pytest.raises(DatabaseError), transaction.atomic():
            ApplicationTechnicalRecord.spike_unfiltered_objects.filter(id=APP_RECORD_A).update(
                organization_id=synthetic_rows.b
            )
    evidence.record("column_privilege_normal_save", "rejected_unchanged_organization_column")
    evidence.record("column_privilege_update_fields", "succeeded")
    evidence.record("application_organization_update", "rejected_by_column_privilege")
