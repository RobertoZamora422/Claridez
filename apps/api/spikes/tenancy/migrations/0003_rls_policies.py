"""Habilitar RLS y un lector fail-closed del GUC experimental."""

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION claridez_spike_current_organization_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    raw_value text;
BEGIN
    raw_value := NULLIF(current_setting('claridez.organization_id', true), '');
    IF raw_value IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        RETURN raw_value::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN NULL;
    END;
END;
$function$;

REVOKE ALL ON FUNCTION claridez_spike_current_organization_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claridez_spike_current_organization_id()
    TO claridez_migrator, claridez_app, claridez_test_runner;

ALTER TABLE claridez_spike_rls_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE claridez_spike_rls_child ENABLE ROW LEVEL SECURITY;
ALTER TABLE claridez_spike_rls_default_deny ENABLE ROW LEVEL SECURITY;

CREATE POLICY spike_rls_record_tenant_policy ON claridez_spike_rls_record
    FOR ALL
    TO claridez_migrator, claridez_app, claridez_test_runner
    USING (organization_id = claridez_spike_current_organization_id())
    WITH CHECK (organization_id = claridez_spike_current_organization_id());

CREATE POLICY spike_rls_child_tenant_policy ON claridez_spike_rls_child
    FOR ALL
    TO claridez_migrator, claridez_app, claridez_test_runner
    USING (organization_id = claridez_spike_current_organization_id())
    WITH CHECK (organization_id = claridez_spike_current_organization_id());
"""

REVERSE_SQL = """
DROP POLICY IF EXISTS spike_rls_child_tenant_policy ON claridez_spike_rls_child;
DROP POLICY IF EXISTS spike_rls_record_tenant_policy ON claridez_spike_rls_record;
ALTER TABLE claridez_spike_rls_default_deny DISABLE ROW LEVEL SECURITY;
ALTER TABLE claridez_spike_rls_child DISABLE ROW LEVEL SECURITY;
ALTER TABLE claridez_spike_rls_record DISABLE ROW LEVEL SECURITY;
DROP FUNCTION IF EXISTS claridez_spike_current_organization_id();
"""


class Migration(migrations.Migration):
    dependencies = [("tenancy_spike", "0002_tenant_integrity_constraints")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
