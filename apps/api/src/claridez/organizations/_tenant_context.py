"""Primitivas PostgreSQL privadas para el contexto tenant local a transacción."""

from django.db import connection

TENANT_GUC = "claridez.organization_id"


def _set_local_organization_context(organization_id: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", (TENANT_GUC,))
        previous = cursor.fetchone()[0]
        cursor.execute("SELECT set_config(%s, %s, true)", (TENANT_GUC, organization_id))
    return previous if isinstance(previous, str) else None


def _restore_local_organization_context(previous: str | None) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", (TENANT_GUC, previous or ""))
