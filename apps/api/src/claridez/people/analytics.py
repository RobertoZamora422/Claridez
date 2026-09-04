"""Resolución histórica batch de clusters People para P15."""

from __future__ import annotations

from uuid import UUID

from claridez.organizations.analytics_contracts import (
    CanonicalCluster,
    Coverage,
    SourceCollection,
    SourceMetricQuery,
    TemporalMode,
    evidence_watermark,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import Person, PersonMerge


def canonical_clusters_as_of(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
    person_ids: tuple[UUID, ...],
) -> SourceCollection[CanonicalCluster]:
    authorization.require(Capability.PERSON_RESOLVE_ANALYTICS)
    if (
        query.as_of_at is None
        or query.source_metric_id != "people.canonical_cluster_as_of"
        or query.mode not in {TemporalMode.STATE, TemporalMode.COHORT}
    ):
        raise ValueError("la resolución histórica exige as_of_at")
    unique_ids = tuple(dict.fromkeys(person_ids))
    existing = set(
        Person.objects.filter(
            organization_id=authorization.organization_id,
            pk__in=unique_ids,
            created_at__lte=min(query.as_of_at, query.knowledge_cutoff_at),
        ).values_list("id", flat=True)
    )
    merges = tuple(
        PersonMerge.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=min(query.as_of_at, query.knowledge_cutoff_at),
        ).values("source_person_id", "target_person_id", "source_revision", "created_at")
    )
    parent = {row["source_person_id"]: row for row in merges}
    materialized: list[CanonicalCluster] = []
    for person_id in unique_ids:
        if person_id not in existing:
            continue
        current = person_id
        seen: set[UUID] = set()
        source_revision: int | None = None
        merged_at = None
        while current in parent and current not in seen:
            seen.add(current)
            row = parent[current]
            source_revision = row["source_revision"]
            merged_at = max(value for value in (merged_at, row["created_at"]) if value is not None)
            current = row["target_person_id"]
        materialized.append(
            CanonicalCluster(
                person_id=person_id,
                canonical_person_id=current,
                source_revision=source_revision,
                merge_recorded_at=merged_at,
            )
        )
    missing = len(materialized) != len(unique_ids)
    return SourceCollection(
        "people.canonical_cluster_as_of",
        1,
        tuple(materialized),
        Coverage.PARTIAL
        if missing and materialized
        else Coverage.UNAVAILABLE
        if missing
        else Coverage.COMPLETE,
        min(
            (row.merge_recorded_at for row in materialized if row.merge_recorded_at is not None),
            default=None,
        ),
        "person_not_visible_at_cutoff" if missing else None,
        tuple(
            f"people.PersonMerge:{row['source_person_id']}:{row['source_revision']}:{row['created_at']}"
            for row in merges
        ),
        evidence_watermark(
            tuple(
                f"{row.person_id}:{row.canonical_person_id}:{row.source_revision}:{row.merge_recorded_at}"
                for row in materialized
            )
        ),
    )
