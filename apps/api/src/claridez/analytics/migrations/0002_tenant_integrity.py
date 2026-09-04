"""P15 aditiva: aislamiento forzado, identidades tenant-aware y ledgers inmutables."""

from django.db import migrations

TABLES = (
    "analytics_reportdefinition",
    "analytics_reportrevision",
    "analytics_reportexecution",
    "analytics_executionmanifest",
    "analytics_exportjob",
    "analytics_exportattempt",
    "analytics_exportartifact",
    "analytics_analyticsauditevent",
)
APPEND_ONLY = tuple(
    table
    for table in TABLES
    if table
    not in {
        "analytics_reportdefinition",
        "analytics_exportjob",
    }
)
RELATIONS = (
    ("reportdefinition", "owner_membership_id", "organizations_membership"),
    ("reportrevision", "authored_by_membership_id", "organizations_membership"),
    ("reportrevision", "report_id", "analytics_reportdefinition"),
    ("reportexecution", "requested_by_membership_id", "organizations_membership"),
    ("reportexecution", "report_revision_id", "analytics_reportrevision"),
    ("executionmanifest", "execution_id", "analytics_reportexecution"),
    ("exportjob", "execution_id", "analytics_reportexecution"),
    ("exportjob", "requested_by_membership_id", "organizations_membership"),
    ("exportattempt", "job_id", "analytics_exportjob"),
    ("exportartifact", "job_id", "analytics_exportjob"),
    ("analyticsauditevent", "actor_membership_id", "organizations_membership"),
)


def security_sql() -> str:
    statements = [
        r"""
    CREATE FUNCTION analytics_deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'analytics historical records are immutable' USING ERRCODE = '23514';
    END; $$;
    """
    ]
    for table in TABLES:
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (organization_id = "
            "NULLIF(current_setting('claridez.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = "
            "NULLIF(current_setting('claridez.organization_id', true), '')::uuid);",
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC, claridez_app;",
            f"GRANT SELECT, INSERT ON TABLE {table} TO claridez_app;",
            f"CREATE TRIGGER analytics_deny_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION analytics_deny_mutation();",
            f"CREATE TRIGGER analytics_deny_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION analytics_deny_mutation();",
        ]
        if table in APPEND_ONLY:
            statements.append(
                f"CREATE TRIGGER analytics_deny_update BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION analytics_deny_mutation();"
            )
        else:
            statements.append(f"GRANT UPDATE ON TABLE {table} TO claridez_app;")
    for index, (table, column, target) in enumerate(RELATIONS):
        statements.append(
            f"ALTER TABLE analytics_{table} ADD CONSTRAINT analytics_tenant_fk_{index} "
            f"FOREIGN KEY (organization_id, {column}) REFERENCES {target}(organization_id, id) "
            "DEFERRABLE INITIALLY DEFERRED;"
        )
    return "\n".join(statements)


INTEGRITY_SQL = r"""
ALTER TABLE analytics_reportdefinition ADD CONSTRAINT analytics_current_revision_fk
FOREIGN KEY (organization_id, id, current_revision)
REFERENCES analytics_reportrevision(organization_id, report_id, number)
DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION analytics_guard_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        ROW(NEW.id, NEW.organization_id, NEW.owner_membership_id, NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id, OLD.organization_id, OLD.owner_membership_id, OLD.created_at)
        OR NEW.current_revision NOT IN (OLD.current_revision, OLD.current_revision + 1)
    ) THEN
        RAISE EXCEPTION 'report identity or revision invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER analytics_report_guard BEFORE UPDATE ON analytics_reportdefinition
FOR EACH ROW EXECUTE FUNCTION analytics_guard_report();

CREATE FUNCTION analytics_guard_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE next_number integer;
BEGIN
    PERFORM 1 FROM analytics_reportdefinition
        WHERE organization_id = NEW.organization_id AND id = NEW.report_id FOR UPDATE;
    SELECT COALESCE(MAX(number), 0) + 1 INTO next_number FROM analytics_reportrevision
        WHERE organization_id = NEW.organization_id AND report_id = NEW.report_id;
    IF NEW.number <> next_number OR jsonb_typeof(NEW.selection) <> 'array'
        OR jsonb_array_length(NEW.selection) NOT BETWEEN 1 AND 53
        OR NEW.definition_sha256 !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'report revision invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER analytics_revision_guard BEFORE INSERT ON analytics_reportrevision
FOR EACH ROW EXECUTE FUNCTION analytics_guard_revision();

CREATE FUNCTION analytics_guard_execution() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb;
BEGIN
    IF NEW.knowledge_cutoff_at > NEW.executed_at OR NEW.executed_at > clock_timestamp()
        OR NEW.result_sha256 !~ '^[a-f0-9]{64}$' OR NEW.catalog_sha256 !~ '^[a-f0-9]{64}$'
        OR NEW.request_sha256 !~ '^[a-f0-9]{64}$' OR NEW.catalog_version <> 'p15-v1'
        OR jsonb_typeof(NEW.selection) <> 'array'
        OR jsonb_array_length(NEW.selection) NOT BETWEEN 1 AND 53
        OR NEW.result_snapshot->'selection' IS DISTINCT FROM NEW.selection
        OR NEW.result_snapshot->>'catalog_hash' IS DISTINCT FROM NEW.catalog_sha256
        OR (NEW.result_snapshot->>'knowledge_cutoff_at')::timestamptz
            IS DISTINCT FROM NEW.knowledge_cutoff_at
        OR (NEW.result_snapshot->>'executed_at')::timestamptz IS DISTINCT FROM NEW.executed_at
        OR NEW.result_snapshot->>'timezone' IS DISTINCT FROM NEW.timezone_name THEN
        RAISE EXCEPTION 'execution evidence invalid' USING ERRCODE = '23514';
    END IF;
    IF NEW.report_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM analytics_reportrevision r WHERE r.organization_id = NEW.organization_id
        AND r.id = NEW.report_revision_id AND r.selection = NEW.selection
        AND r.timezone_name = NEW.timezone_name
    ) THEN
        RAISE EXCEPTION 'execution does not match report revision' USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(NEW.selection) LOOP
        IF item->>'metric_version' <> '1'
            OR ((item->>'as_of_at') IS NOT NULL
                AND (item->>'as_of_at')::timestamptz > NEW.knowledge_cutoff_at) THEN
            RAISE EXCEPTION 'execution metric temporal order invalid' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END; $$;
CREATE TRIGGER analytics_execution_guard BEFORE INSERT ON analytics_reportexecution
FOR EACH ROW EXECUTE FUNCTION analytics_guard_execution();

CREATE FUNCTION analytics_guard_job() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mutable_fields text[] := ARRAY[
    'state', 'attempt_count', 'next_attempt_at', 'lease_token', 'lease_expires_at',
    'last_error_code', 'completed_at', 'updated_at'];
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'queued' OR NEW.attempt_count <> 0 OR NEW.last_error_code <> ''
            OR NEW.request_sha256 !~ '^[a-f0-9]{64}$' THEN
            RAISE EXCEPTION 'new export job invalid' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - mutable_fields) IS DISTINCT FROM (to_jsonb(OLD) - mutable_fields)
        OR OLD.state IN ('completed', 'terminal') THEN
        RAISE EXCEPTION 'export job identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.state = 'running' THEN
        IF NOT (OLD.state IN ('queued', 'retry')
            OR (OLD.state = 'running' AND OLD.lease_expires_at <= clock_timestamp()))
            OR (OLD.state IN ('queued', 'retry') AND OLD.next_attempt_at > clock_timestamp())
            OR NEW.attempt_count <> OLD.attempt_count + 1
            OR NEW.lease_token IS NOT DISTINCT FROM OLD.lease_token
            OR NEW.lease_expires_at <= clock_timestamp() THEN
            RAISE EXCEPTION 'export claim or reclaim invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.state IN ('completed', 'retry', 'terminal') THEN
        IF OLD.state <> 'running' OR NEW.attempt_count <> OLD.attempt_count
            OR (OLD.lease_expires_at <= clock_timestamp() AND NOT (
                NEW.state = 'terminal' AND NEW.last_error_code = 'attempt_budget_exhausted'
                AND OLD.attempt_count >= 5)) THEN
            RAISE EXCEPTION 'export finalization invalid' USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'completed' AND NOT EXISTS (
            SELECT 1 FROM analytics_exportartifact WHERE organization_id = NEW.organization_id
                AND job_id = NEW.id AND id = NEW.artifact_identity
        ) THEN
            RAISE EXCEPTION 'completed export requires published metadata' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'export state transition invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER analytics_job_guard BEFORE INSERT OR UPDATE ON analytics_exportjob
FOR EACH ROW EXECUTE FUNCTION analytics_guard_job();

CREATE FUNCTION analytics_guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.sha256 !~ '^[a-f0-9]{64}$'
        OR NEW.object_key !~ '^[a-f0-9]{2}/[a-f0-9]{64}[.](csv|xlsx|pdf)$'
        OR NOT EXISTS (SELECT 1 FROM analytics_exportjob j
            WHERE j.organization_id = NEW.organization_id AND j.id = NEW.job_id
                AND j.artifact_identity = NEW.id AND j.format = NEW.format
                AND j.renderer_version = NEW.renderer_version AND j.state = 'running'
                AND j.lease_expires_at > clock_timestamp()) THEN
        RAISE EXCEPTION 'artifact identity or publication metadata invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER analytics_artifact_guard BEFORE INSERT ON analytics_exportartifact
FOR EACH ROW EXECUTE FUNCTION analytics_guard_artifact();

CREATE FUNCTION analytics_guard_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target analytics_exportjob;
BEGIN
    SELECT * INTO target FROM analytics_exportjob
        WHERE organization_id = NEW.organization_id AND id = NEW.job_id;
    IF NOT FOUND OR NEW.number <> target.attempt_count OR NEW.lease_token <> target.lease_token
        OR target.state <> 'running' THEN
        RAISE EXCEPTION 'attempt must belong to current tenant lease' USING ERRCODE = '23514';
    END IF;
    IF (NEW.event = 'reclaimed' AND target.lease_expires_at > clock_timestamp())
        OR (NEW.event IN ('claimed', 'completed', 'retry')
            AND target.lease_expires_at <= clock_timestamp()) THEN
        RAISE EXCEPTION 'attempt lease timing invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER analytics_attempt_guard BEFORE INSERT ON analytics_exportattempt
FOR EACH ROW EXECUTE FUNCTION analytics_guard_attempt();
"""


def reverse_sql() -> str:
    statements = []
    for table in TABLES:
        for trigger in (
            "analytics_deny_delete",
            "analytics_deny_truncate",
            "analytics_deny_update",
        ):
            statements.append(f"DROP TRIGGER IF EXISTS {trigger} ON {table};")
        statements += [
            f"DROP POLICY {table}_tenant ON {table};",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
            f"REVOKE ALL ON TABLE {table} FROM claridez_app;",
        ]
    for table, trigger in (
        ("reportdefinition", "report"),
        ("reportrevision", "revision"),
        ("reportexecution", "execution"),
        ("exportjob", "job"),
        ("exportartifact", "artifact"),
        ("exportattempt", "attempt"),
    ):
        statements += [
            f"DROP TRIGGER analytics_{trigger}_guard ON analytics_{table};",
            f"DROP FUNCTION analytics_guard_{trigger}();",
        ]
    for index, (table, _, _) in enumerate(RELATIONS):
        statements.append(
            f"ALTER TABLE analytics_{table} DROP CONSTRAINT analytics_tenant_fk_{index};"
        )
    statements += [
        "ALTER TABLE analytics_reportdefinition DROP CONSTRAINT analytics_current_revision_fk;",
        "DROP FUNCTION analytics_deny_mutation();",
    ]
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("analytics", "0001_initial")]
    operations = [migrations.RunSQL(security_sql() + INTEGRITY_SQL, reverse_sql=reverse_sql())]
