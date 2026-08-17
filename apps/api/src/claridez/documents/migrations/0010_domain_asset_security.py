from django.db import migrations

TABLES = (
    "documents_privatedomainfile",
    "documents_privatedomainfileevent",
    "documents_privatedomainscanattempt",
    "documents_generateddomainartifact",
)


def _rls_sql() -> str:
    statements: list[str] = []
    for table in TABLES:
        statements.extend(
            [
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                f"DROP POLICY IF EXISTS {table}_tenant_policy ON public.{table};",
                (
                    f"CREATE POLICY {table}_tenant_policy ON public.{table} "
                    "USING (organization_id = public.claridez_current_organization_id()) "
                    "WITH CHECK (organization_id = public.claridez_current_organization_id());"
                ),
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC;",
                f"REVOKE ALL ON TABLE public.{table} FROM claridez_app;",
                f"GRANT SELECT, INSERT ON TABLE public.{table} TO claridez_app;",
                f"GRANT ALL PRIVILEGES ON TABLE public.{table} TO claridez_test_runner;",
                f"GRANT ALL PRIVILEGES ON TABLE public.{table} TO claridez_migrator;",
            ]
        )
    statements.extend(
        [
            "GRANT UPDATE ON TABLE public.documents_privatedomainfile TO claridez_app;",
            "GRANT UPDATE ON TABLE public.documents_generateddomainartifact TO claridez_app;",
        ]
    )
    return "\n".join(statements)


def _rls_reverse_sql() -> str:
    statements: list[str] = []
    for table in reversed(TABLES):
        statements.extend(
            [
                f"DROP POLICY IF EXISTS {table}_tenant_policy ON public.{table};",
                f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;",
            ]
        )
    return "\n".join(statements)


TENANT_FKS_SQL = """
ALTER TABLE public.documents_privatedomainfile
ADD CONSTRAINT docs_domainfile_actor_fk
FOREIGN KEY (organization_id, uploaded_by_membership_id)
REFERENCES public.organizations_membership (organization_id, id);

ALTER TABLE public.documents_privatedomainfileevent
ADD CONSTRAINT docs_domainfile_event_file_fk
FOREIGN KEY (organization_id, domain_file_id)
REFERENCES public.documents_privatedomainfile (organization_id, id);

ALTER TABLE public.documents_privatedomainscanattempt
ADD CONSTRAINT docs_domainscan_file_fk
FOREIGN KEY (organization_id, domain_file_id)
REFERENCES public.documents_privatedomainfile (organization_id, id);
"""

TENANT_FKS_REVERSE_SQL = """
ALTER TABLE public.documents_privatedomainscanattempt
DROP CONSTRAINT IF EXISTS docs_domainscan_file_fk;
ALTER TABLE public.documents_privatedomainfileevent
DROP CONSTRAINT IF EXISTS docs_domainfile_event_file_fk;
ALTER TABLE public.documents_privatedomainfile
DROP CONSTRAINT IF EXISTS docs_domainfile_actor_fk;
"""

GUARDS_SQL = """
CREATE OR REPLACE FUNCTION public.claridez_documents_domain_immutable()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'document domain evidence is append-only' USING ERRCODE = '55000';
    END IF;
    RAISE EXCEPTION 'document domain evidence is immutable' USING ERRCODE = '55000';
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_documents_domain_file_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF (NEW.id, NEW.organization_id, NEW.owner_domain, NEW.owner_id, NEW.purpose,
        NEW.display_name, NEW.storage_key, NEW.declared_media_type, NEW.extension,
        NEW.sha256, NEW.size_bytes, NEW.uploaded_by_membership_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.organization_id, OLD.owner_domain, OLD.owner_id, OLD.purpose,
        OLD.display_name, OLD.storage_key, OLD.declared_media_type, OLD.extension,
        OLD.sha256, OLD.size_bytes, OLD.uploaded_by_membership_id, OLD.created_at) THEN
        RAISE EXCEPTION 'document domain file identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF NOT (
        (OLD.state = 'uploading' AND NEW.state IN ('uploading', 'quarantined', 'rejected')) OR
        (OLD.state = 'quarantined' AND NEW.state IN ('quarantined', 'pending_scan')) OR
        (OLD.state = 'pending_scan' AND NEW.state IN
            ('pending_scan', 'clean', 'infected', 'rejected', 'scan_error')) OR
        (OLD.state = 'scan_error' AND NEW.state IN
            ('scan_error', 'clean', 'infected', 'rejected')) OR
        (OLD.state = 'clean' AND NEW.state IN ('clean', 'integrity_failed')) OR
        (OLD.state IN ('infected', 'rejected', 'integrity_failed') AND NEW.state = OLD.state)
    ) THEN
        RAISE EXCEPTION 'invalid document domain file transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claridez_documents_domain_artifact_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF (NEW.id, NEW.organization_id, NEW.owner_domain, NEW.owner_id, NEW.purpose,
        NEW.source_snapshot_sha256, NEW.render_payload, NEW.media_type, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.organization_id, OLD.owner_domain, OLD.owner_id, OLD.purpose,
        OLD.source_snapshot_sha256, OLD.render_payload, OLD.media_type, OLD.created_at) THEN
        RAISE EXCEPTION 'document domain artifact source is immutable' USING ERRCODE = '55000';
    END IF;
    IF NOT (
        (OLD.state = 'pending_render' AND NEW.state IN
            ('pending_render', 'available', 'render_failed')) OR
        (OLD.state = 'available' AND NEW.state IN ('available', 'integrity_failed')) OR
        (OLD.state IN ('render_failed', 'integrity_failed') AND NEW.state = OLD.state)
    ) THEN
        RAISE EXCEPTION 'invalid document domain artifact transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION public.claridez_documents_domain_immutable() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_documents_domain_file_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claridez_documents_domain_artifact_update() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_documents_domain_immutable(),
    public.claridez_documents_domain_file_update(),
    public.claridez_documents_domain_artifact_update()
TO claridez_app, claridez_test_runner, claridez_migrator;

CREATE TRIGGER documents_domainfile_update_guard
BEFORE UPDATE ON public.documents_privatedomainfile
FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_domain_file_update();
CREATE TRIGGER documents_domainfile_delete_guard
BEFORE DELETE ON public.documents_privatedomainfile
FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_domain_immutable();
CREATE TRIGGER documents_domainfile_event_guard
BEFORE UPDATE OR DELETE ON public.documents_privatedomainfileevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_domain_immutable();
CREATE TRIGGER documents_domainscan_guard
BEFORE UPDATE OR DELETE ON public.documents_privatedomainscanattempt
FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_domain_immutable();
CREATE TRIGGER documents_domainartifact_update_guard
BEFORE UPDATE ON public.documents_generateddomainartifact
FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_domain_artifact_update();
CREATE TRIGGER documents_domainartifact_delete_guard
BEFORE DELETE ON public.documents_generateddomainartifact
FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_domain_immutable();
"""

GUARDS_REVERSE_SQL = """
DROP TRIGGER IF EXISTS documents_domainartifact_delete_guard
ON public.documents_generateddomainartifact;
DROP TRIGGER IF EXISTS documents_domainartifact_update_guard
ON public.documents_generateddomainartifact;
DROP TRIGGER IF EXISTS documents_domainscan_guard
ON public.documents_privatedomainscanattempt;
DROP TRIGGER IF EXISTS documents_domainfile_event_guard
ON public.documents_privatedomainfileevent;
DROP TRIGGER IF EXISTS documents_domainfile_delete_guard
ON public.documents_privatedomainfile;
DROP TRIGGER IF EXISTS documents_domainfile_update_guard
ON public.documents_privatedomainfile;
DROP FUNCTION IF EXISTS public.claridez_documents_domain_artifact_update();
DROP FUNCTION IF EXISTS public.claridez_documents_domain_file_update();
DROP FUNCTION IF EXISTS public.claridez_documents_domain_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0009_alter_documentjob_job_type_privatedomainfile_and_more")]

    operations = [
        migrations.RunSQL(TENANT_FKS_SQL, TENANT_FKS_REVERSE_SQL),
        migrations.RunSQL(_rls_sql(), _rls_reverse_sql()),
        migrations.RunSQL(GUARDS_SQL, GUARDS_REVERSE_SQL),
    ]
