"""Comparar rutas soportadas con bypasses deliberados sin RLS."""

from __future__ import annotations

import pytest
from django.db import connections

from spikes.tenancy.context import (
    TenantContextRequired,
    ValidatedTechnicalOrganization,
    tenant_scope,
)
from spikes.tenancy.models import ApplicationTechnicalRecord
from spikes.tenancy.services import (
    TenantObjectNotFound,
    bulk_create_private_records,
    bulk_update_payload,
    create_private_record,
    get_private_record,
    tenant_queryset,
)
from spikes.tenancy.tests.conftest import (
    APP_RECORD_A,
    APP_RECORD_B,
    EvidenceRecorder,
    Organizations,
)

pytestmark = pytest.mark.tenancy_spike


def test_supported_routes_filter_reads_and_writes(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        assert tenant_queryset(ApplicationTechnicalRecord).count() == 1
        with pytest.raises(TenantObjectNotFound):
            get_private_record(ApplicationTechnicalRecord, APP_RECORD_B)
        created = create_private_record(
            ApplicationTechnicalRecord,
            external_key="supported-create",
            payload="synthetic",
        )
        assert created.organization_id == synthetic_rows.a
        bulk_create_private_records(
            ApplicationTechnicalRecord,
            [{"external_key": "bulk-a", "payload": "synthetic"}],
        )
        assert bulk_update_payload(ApplicationTechnicalRecord, payload="updated") == 3

    assert ApplicationTechnicalRecord.objects.count() == 0
    with pytest.raises(TenantContextRequired):
        create_private_record(
            ApplicationTechnicalRecord,
            external_key="missing-context",
            payload="synthetic",
        )
    evidence.record("application_supported_routes", "isolated")
    evidence.record("application_missing_context_reads", 0)

    with (
        tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.b)),
        pytest.raises(TenantObjectNotFound),
    ):
        get_private_record(ApplicationTechnicalRecord, APP_RECORD_A)
    evidence.record("application_bidirectional_cross_lookup", "indistinguishable_not_found")


def test_deliberate_bypasses_show_residual_application_risk(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    exposed_counts: dict[str, int] = {}
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        exposed_counts["unfiltered_manager"] = (
            ApplicationTechnicalRecord.spike_unfiltered_objects.count()
        )
        exposed_counts["base_manager"] = ApplicationTechnicalRecord._base_manager.count()
        exposed_counts["raw"] = len(
            list(
                ApplicationTechnicalRecord.spike_unfiltered_objects.raw(
                    "SELECT * FROM claridez_spike_app_record"
                )
            )
        )
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT count(*) FROM claridez_spike_app_record")
            exposed_counts["cursor"] = int(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO claridez_spike_app_record "
                "(id, organization_id, external_key, payload) "
                "VALUES (gen_random_uuid(), %s, %s, %s)",
                (synthetic_rows.b, "unsafe-sql", "synthetic"),
            )
        ApplicationTechnicalRecord.spike_unfiltered_objects.bulk_create(
            [
                ApplicationTechnicalRecord(
                    organization_id=synthetic_rows.b,
                    external_key="unsafe-bulk",
                    payload="synthetic",
                )
            ]
        )
    assert all(count >= 2 for count in exposed_counts.values())
    assert (
        ApplicationTechnicalRecord.spike_unfiltered_objects.filter(
            external_key="unsafe-bulk", organization_id=synthetic_rows.b
        ).count()
        == 1
    )
    evidence.record("application_bypass_potential_rows", exposed_counts)
    evidence.record("application_unvalidated_bulk", "cross_tenant_write_succeeded")
    evidence.record("application_unvalidated_direct_sql", "cross_tenant_write_succeeded")
