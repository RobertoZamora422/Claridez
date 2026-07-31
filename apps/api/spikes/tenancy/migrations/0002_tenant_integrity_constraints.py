"""Añadir relaciones compuestas que Django 5.2 no representa como ForeignKey pública."""

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE claridez_spike_app_child
    ADD CONSTRAINT spike_app_child_parent_tenant_fk
    FOREIGN KEY (organization_id, parent_id)
    REFERENCES claridez_spike_app_record (organization_id, id)
    ON DELETE CASCADE;

ALTER TABLE claridez_spike_rls_child
    ADD CONSTRAINT spike_rls_child_parent_tenant_fk
    FOREIGN KEY (organization_id, parent_id)
    REFERENCES claridez_spike_rls_record (organization_id, id)
    ON DELETE CASCADE;
"""

REVERSE_SQL = """
ALTER TABLE claridez_spike_rls_child
    DROP CONSTRAINT IF EXISTS spike_rls_child_parent_tenant_fk;
ALTER TABLE claridez_spike_app_child
    DROP CONSTRAINT IF EXISTS spike_app_child_parent_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("tenancy_spike", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)],
            state_operations=[],
        )
    ]
