"""Puerto público estrecho de identidad de personas."""

from .errors import PeopleError
from .services import (
    canonical_cluster_ids,
    canonical_person_id,
    create_person,
    get_person_raw,
    list_consents,
    list_people,
    list_person_revisions,
    read_person,
    require_canonical_person,
    update_person,
)

__all__ = (
    "PeopleError",
    "canonical_cluster_ids",
    "canonical_person_id",
    "create_person",
    "get_person_raw",
    "list_consents",
    "list_people",
    "list_person_revisions",
    "read_person",
    "require_canonical_person",
    "update_person",
)
