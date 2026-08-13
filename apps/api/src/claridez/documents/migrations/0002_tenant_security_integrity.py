from django.db import migrations

PRIVATE_TABLES = (
    "documents_documenttemplate",
    "documents_documenttemplateversion",
    "documents_templateevent",
    "documents_contractualrecord",
    "documents_contractualinstrument",
    "documents_issuedinstrumentversion",
    "documents_generatedartifact",
    "documents_artifactintegrityevent",
    "documents_externalfile",
    "documents_externalfileevent",
    "documents_malwarescanattempt",
    "documents_externalaccessgrant",
    "documents_externaldocumentsession",
    "documents_acceptancechallenge",
    "documents_acceptanceevidence",
    "documents_externalaccessevent",
    "documents_retentionpolicy",
    "documents_retentionassignment",
    "documents_legalhold",
    "documents_retentionevent",
    "documents_documentjob",
    "documents_documentjobattempt",
)

APPEND_ONLY_TABLES = (
    "documents_templateevent",
    "documents_artifactintegrityevent",
    "documents_externalfileevent",
    "documents_malwarescanattempt",
    "documents_acceptanceevidence",
    "documents_externalaccessevent",
    "documents_retentionevent",
    "documents_documentjobattempt",
)

APP_INSERT_ONLY = set(APPEND_ONLY_TABLES)
APP_MUTABLE = set(PRIVATE_TABLES) - APP_INSERT_ONLY

TENANT_FOREIGN_KEYS = (
    (
        "documents_contractualrecord",
        "root_reservation_id",
        "commercial_reservation",
        "doc_record_root_fk",
    ),
    (
        "documents_contractualrecord",
        "created_by_membership_id",
        "organizations_membership",
        "doc_record_creator_fk",
    ),
    (
        "documents_contractualinstrument",
        "record_id",
        "documents_contractualrecord",
        "doc_instrument_record_fk",
    ),
    (
        "documents_contractualinstrument",
        "created_by_membership_id",
        "organizations_membership",
        "doc_instrument_creator_fk",
    ),
    (
        "documents_documenttemplateversion",
        "template_id",
        "documents_documenttemplate",
        "doc_template_version_template_fk",
    ),
    (
        "documents_documenttemplateversion",
        "published_by_membership_id",
        "organizations_membership",
        "doc_template_version_publisher_fk",
    ),
    (
        "documents_templateevent",
        "template_id",
        "documents_documenttemplate",
        "doc_template_event_template_fk",
    ),
    (
        "documents_templateevent",
        "template_version_id",
        "documents_documenttemplateversion",
        "doc_template_event_version_fk",
    ),
    (
        "documents_templateevent",
        "actor_membership_id",
        "organizations_membership",
        "doc_template_event_actor_fk",
    ),
    (
        "documents_issuedinstrumentversion",
        "instrument_id",
        "documents_contractualinstrument",
        "doc_issued_instrument_fk",
    ),
    (
        "documents_issuedinstrumentversion",
        "current_reservation_id",
        "commercial_reservation",
        "doc_issued_reservation_fk",
    ),
    (
        "documents_issuedinstrumentversion",
        "quotation_version_id",
        "commercial_quotationversion",
        "doc_issued_quotation_fk",
    ),
    (
        "documents_issuedinstrumentversion",
        "template_version_id",
        "documents_documenttemplateversion",
        "doc_issued_template_version_fk",
    ),
    (
        "documents_issuedinstrumentversion",
        "issued_by_membership_id",
        "organizations_membership",
        "doc_issued_actor_fk",
    ),
    (
        "documents_generatedartifact",
        "issued_version_id",
        "documents_issuedinstrumentversion",
        "doc_artifact_issued_fk",
    ),
    (
        "documents_artifactintegrityevent",
        "artifact_id",
        "documents_generatedartifact",
        "doc_integrity_artifact_fk",
    ),
    (
        "documents_externalfile",
        "record_id",
        "documents_contractualrecord",
        "doc_external_file_record_fk",
    ),
    (
        "documents_externalfile",
        "uploaded_by_membership_id",
        "organizations_membership",
        "doc_external_file_actor_fk",
    ),
    (
        "documents_externalfileevent",
        "external_file_id",
        "documents_externalfile",
        "doc_external_file_event_fk",
    ),
    (
        "documents_malwarescanattempt",
        "external_file_id",
        "documents_externalfile",
        "doc_malware_file_fk",
    ),
    (
        "documents_externalaccessgrant",
        "issued_version_id",
        "documents_issuedinstrumentversion",
        "doc_grant_issued_fk",
    ),
    (
        "documents_externalaccessgrant",
        "artifact_id",
        "documents_generatedartifact",
        "doc_grant_artifact_fk",
    ),
    (
        "documents_externalaccessgrant",
        "created_by_membership_id",
        "organizations_membership",
        "doc_grant_creator_fk",
    ),
    (
        "documents_externalaccessgrant",
        "revoked_by_membership_id",
        "organizations_membership",
        "doc_grant_revoker_fk",
    ),
    (
        "documents_externaldocumentsession",
        "grant_id",
        "documents_externalaccessgrant",
        "doc_session_grant_fk",
    ),
    (
        "documents_acceptancechallenge",
        "grant_id",
        "documents_externalaccessgrant",
        "doc_challenge_grant_fk",
    ),
    (
        "documents_acceptancechallenge",
        "issued_version_id",
        "documents_issuedinstrumentversion",
        "doc_challenge_issued_fk",
    ),
    (
        "documents_acceptancechallenge",
        "artifact_id",
        "documents_generatedartifact",
        "doc_challenge_artifact_fk",
    ),
    (
        "documents_acceptanceevidence",
        "challenge_id",
        "documents_acceptancechallenge",
        "doc_acceptance_challenge_fk",
    ),
    (
        "documents_acceptanceevidence",
        "issued_version_id",
        "documents_issuedinstrumentversion",
        "doc_acceptance_issued_fk",
    ),
    (
        "documents_acceptanceevidence",
        "artifact_id",
        "documents_generatedartifact",
        "doc_acceptance_artifact_fk",
    ),
    (
        "documents_externalaccessevent",
        "grant_id",
        "documents_externalaccessgrant",
        "doc_access_event_grant_fk",
    ),
    (
        "documents_externalaccessevent",
        "challenge_id",
        "documents_acceptancechallenge",
        "doc_access_event_challenge_fk",
    ),
    (
        "documents_retentionpolicy",
        "approved_by_membership_id",
        "organizations_membership",
        "doc_retention_policy_actor_fk",
    ),
    (
        "documents_retentionassignment",
        "policy_id",
        "documents_retentionpolicy",
        "doc_retention_assignment_policy_fk",
    ),
    (
        "documents_legalhold",
        "assignment_id",
        "documents_retentionassignment",
        "doc_hold_assignment_fk",
    ),
    (
        "documents_legalhold",
        "placed_by_membership_id",
        "organizations_membership",
        "doc_hold_placer_fk",
    ),
    (
        "documents_legalhold",
        "released_by_membership_id",
        "organizations_membership",
        "doc_hold_releaser_fk",
    ),
    (
        "documents_retentionevent",
        "assignment_id",
        "documents_retentionassignment",
        "doc_retention_event_assignment_fk",
    ),
    (
        "documents_retentionevent",
        "actor_membership_id",
        "organizations_membership",
        "doc_retention_event_actor_fk",
    ),
    ("documents_documentjobattempt", "job_id", "documents_documentjob", "doc_job_attempt_job_fk"),
)


def _rls_sql() -> str:
    statements: list[str] = []
    for table in PRIVATE_TABLES:
        statements.extend(
            [
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                f"DROP POLICY IF EXISTS {table}_tenant ON public.{table};",
                (
                    f"CREATE POLICY {table}_tenant ON public.{table} "
                    "USING (organization_id = public.claridez_current_organization_id()) "
                    "WITH CHECK (organization_id = public.claridez_current_organization_id());"
                ),
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, claridez_app;",
                f"GRANT SELECT ON TABLE public.{table} TO claridez_app;",
            ]
        )
        if table in APP_INSERT_ONLY:
            statements.append(f"GRANT INSERT ON TABLE public.{table} TO claridez_app;")
        else:
            statements.append(f"GRANT INSERT, UPDATE ON TABLE public.{table} TO claridez_app;")
        statements.append(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO claridez_test_runner;"
        )
    statements.extend(
        [
            "REVOKE ALL ON TABLE public.documents_externaltokenlocator FROM PUBLIC, claridez_app;",
            "GRANT SELECT, INSERT ON TABLE public.documents_externaltokenlocator TO claridez_app;",
            (
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                "public.documents_externaltokenlocator TO claridez_test_runner;"
            ),
            (
                "REVOKE ALL ON TABLE public.documents_externalratelimitbucket "
                "FROM PUBLIC, claridez_app;"
            ),
            (
                "GRANT SELECT, INSERT, UPDATE ON TABLE "
                "public.documents_externalratelimitbucket TO claridez_app;"
            ),
            (
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                "public.documents_externalratelimitbucket TO claridez_test_runner;"
            ),
        ]
    )
    return "\n".join(statements)


def _tenant_fks_sql() -> str:
    return "\n".join(
        (
            f"ALTER TABLE public.{table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY (organization_id, {column}) "
            f"REFERENCES public.{target} (organization_id, id) DEFERRABLE INITIALLY DEFERRED;"
        )
        for table, column, target, name in TENANT_FOREIGN_KEYS
    )


def _tenant_fks_reverse_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name};"
        for table, _column, _target, name in reversed(TENANT_FOREIGN_KEYS)
    )


def _rls_reverse_sql() -> str:
    return "\n".join(
        statement
        for table in PRIVATE_TABLES
        for statement in (
            f"DROP POLICY IF EXISTS {table}_tenant_policy ON public.{table};",
            f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;",
        )
    )


GUARDS_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_documents_append_only()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    RAISE EXCEPTION 'documentary evidence is append-only' USING ERRCODE = '23514';
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_documents_append_only() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_guard_document_version()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF TG_TABLE_NAME = 'documents_documenttemplateversion' THEN
        IF OLD.status IN ('published', 'inactive')
           AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'published template versions are immutable' USING ERRCODE = '23514';
        END IF;
        IF ROW(NEW.organization_id, NEW.template_id, NEW.version, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.template_id,
                                OLD.version, OLD.created_at) THEN
            RAISE EXCEPTION 'template version identity is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_issuedinstrumentversion' THEN
        IF ROW(NEW.organization_id, NEW.instrument_id, NEW.version,
               NEW.current_reservation_id, NEW.quotation_version_id,
               NEW.template_version_id, NEW.snapshot, NEW.snapshot_schema_version,
               NEW.snapshot_sha256, NEW.resolved_variables, NEW.provenance,
               NEW.materiality_policy_version, NEW.renderer_name,
               NEW.renderer_version, NEW.render_environment, NEW.assets_sha256,
               NEW.idempotency_key, NEW.issued_by_membership_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.instrument_id, OLD.version,
               OLD.current_reservation_id, OLD.quotation_version_id,
               OLD.template_version_id, OLD.snapshot, OLD.snapshot_schema_version,
               OLD.snapshot_sha256, OLD.resolved_variables, OLD.provenance,
               OLD.materiality_policy_version, OLD.renderer_name,
               OLD.renderer_version, OLD.render_environment, OLD.assets_sha256,
               OLD.idempotency_key, OLD.issued_by_membership_id, OLD.created_at) THEN
            RAISE EXCEPTION 'issued version evidence is immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.state = 'issued' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'issued versions are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_generatedartifact' THEN
        IF ROW(NEW.organization_id, NEW.issued_version_id, NEW.storage_key, NEW.sha256,
               NEW.size_bytes, NEW.media_type, NEW.provenance, NEW.renderer_name,
               NEW.renderer_version, NEW.render_environment, NEW.stored_at, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.issued_version_id, OLD.storage_key,
               OLD.sha256, OLD.size_bytes, OLD.media_type, OLD.provenance, OLD.renderer_name,
               OLD.renderer_version, OLD.render_environment, OLD.stored_at, OLD.created_at) THEN
            RAISE EXCEPTION 'artifact evidence is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_contractualrecord' THEN
        RAISE EXCEPTION 'contractual records are immutable' USING ERRCODE = '23514';
    ELSIF TG_TABLE_NAME = 'documents_acceptancechallenge' THEN
        IF ROW(NEW.organization_id, NEW.grant_id, NEW.issued_version_id,
               NEW.artifact_id, NEW.token_hmac, NEW.expires_at, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.grant_id, OLD.issued_version_id,
               OLD.artifact_id, OLD.token_hmac, OLD.expires_at, OLD.created_at) THEN
            RAISE EXCEPTION 'acceptance challenge identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.consumed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'consumed challenges are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_externalfile' THEN
        IF ROW(NEW.organization_id, NEW.record_id, NEW.display_name, NEW.storage_key,
               NEW.declared_media_type, NEW.detected_media_type, NEW.extension,
               NEW.sha256, NEW.size_bytes, NEW.uploaded_by_membership_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.record_id, OLD.display_name,
               OLD.storage_key, OLD.declared_media_type, OLD.detected_media_type,
               OLD.extension, OLD.sha256, OLD.size_bytes, OLD.uploaded_by_membership_id,
               OLD.created_at) THEN
            RAISE EXCEPTION 'external file evidence is immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.state <> OLD.state AND NOT (
            (OLD.state = 'quarantined' AND NEW.state = 'pending_scan') OR
            (OLD.state IN ('pending_scan', 'scan_error') AND
             NEW.state IN ('clean', 'infected', 'rejected', 'scan_error'))
        ) THEN
            RAISE EXCEPTION 'invalid external file transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_document_version() FROM PUBLIC;
"""


def _triggers_sql() -> str:
    statements = [GUARDS_SQL]
    for table in (*APPEND_ONLY_TABLES, "documents_externaltokenlocator"):
        statements.extend(
            [
                f"DROP TRIGGER IF EXISTS {table}_append_only ON public.{table};",
                (
                    f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
                    f"ON public.{table} FOR EACH ROW "
                    "EXECUTE FUNCTION public.claridez_documents_append_only();"
                ),
            ]
        )
    for table in (
        "documents_documenttemplateversion",
        "documents_issuedinstrumentversion",
        "documents_generatedartifact",
        "documents_contractualrecord",
        "documents_acceptancechallenge",
        "documents_externalfile",
    ):
        statements.extend(
            [
                f"DROP TRIGGER IF EXISTS {table}_guard ON public.{table};",
                (
                    f"CREATE TRIGGER {table}_guard BEFORE UPDATE ON public.{table} "
                    "FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_document_version();"
                ),
            ]
        )
    return "\n".join(statements)


def _triggers_reverse_sql() -> str:
    statements: list[str] = []
    for table in (*APPEND_ONLY_TABLES, "documents_externaltokenlocator"):
        statements.append(f"DROP TRIGGER IF EXISTS {table}_append_only ON public.{table};")
    for table in (
        "documents_documenttemplateversion",
        "documents_issuedinstrumentversion",
        "documents_generatedartifact",
        "documents_contractualrecord",
        "documents_acceptancechallenge",
        "documents_externalfile",
    ):
        statements.append(f"DROP TRIGGER IF EXISTS {table}_guard ON public.{table};")
    statements.extend(
        (
            "DROP FUNCTION IF EXISTS public.claridez_documents_append_only();",
            "DROP FUNCTION IF EXISTS public.claridez_guard_document_version();",
        )
    )
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]

    operations = [
        migrations.RunSQL(_tenant_fks_sql(), _tenant_fks_reverse_sql()),
        migrations.RunSQL(_rls_sql(), _rls_reverse_sql()),
        migrations.RunSQL(_triggers_sql(), _triggers_reverse_sql()),
    ]
