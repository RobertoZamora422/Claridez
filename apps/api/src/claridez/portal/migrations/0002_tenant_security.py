# ruff: noqa: E501

from django.db import migrations

PRIVATE_TABLES = (
    "portal_portalauditevent",
    "portal_portalprincipal",
    "portal_portalgrant",
    "portal_portalchallenge",
    "portal_portalsession",
    "portal_publicform",
    "portal_publicformversion",
    "portal_publicformsubmission",
)


def _rls_sql() -> str:
    statements: list[str] = []
    for table in PRIVATE_TABLES:
        statements.extend(
            [
                f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY',
                f'DROP POLICY IF EXISTS "{table}_tenant" ON "{table}"',
                (
                    f'CREATE POLICY "{table}_tenant" ON "{table}" '
                    "USING (organization_id = NULLIF(current_setting('claridez.organization_id', true), '')::uuid) "
                    "WITH CHECK (organization_id = NULLIF(current_setting('claridez.organization_id', true), '')::uuid)"
                ),
                f'REVOKE ALL ON TABLE "{table}" FROM PUBLIC',
                f'REVOKE ALL ON TABLE "{table}" FROM claridez_app',
            ]
        )
    append_only = {"portal_portalauditevent"}
    for table in PRIVATE_TABLES:
        privileges = "SELECT, INSERT" if table in append_only else "SELECT, INSERT, UPDATE"
        statements.append(f'GRANT {privileges} ON TABLE "{table}" TO claridez_app')
    return ";\n".join(statements) + ";"


def _reverse_rls_sql() -> str:
    statements: list[str] = []
    for table in PRIVATE_TABLES:
        statements.extend(
            [
                f'DROP POLICY IF EXISTS "{table}_tenant" ON "{table}"',
                f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY',
                f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY',
                f'REVOKE ALL ON TABLE "{table}" FROM claridez_app',
            ]
        )
    return ";\n".join(statements) + ";"


INTEGRITY_SQL = r"""
ALTER TABLE portal_portalgrant
ADD CONSTRAINT portal_grant_org_principal_fk
FOREIGN KEY (organization_id, principal_id)
REFERENCES portal_portalprincipal(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE portal_portalchallenge
ADD CONSTRAINT portal_challenge_org_principal_fk
FOREIGN KEY (organization_id, principal_id)
REFERENCES portal_portalprincipal(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE portal_portalsession
ADD CONSTRAINT portal_session_org_principal_fk
FOREIGN KEY (organization_id, principal_id)
REFERENCES portal_portalprincipal(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE portal_publicformversion
ADD CONSTRAINT portal_formversion_org_form_fk
FOREIGN KEY (organization_id, form_id)
REFERENCES portal_publicform(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE portal_publicformsubmission
ADD CONSTRAINT portal_submission_org_formversion_fk
FOREIGN KEY (organization_id, form_version_id)
REFERENCES portal_publicformversion(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION portal_guard_form_version_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('published', 'retired') THEN
        IF OLD.status = 'published' AND NEW.status = 'retired'
           AND NEW.retired_at IS NOT NULL
           AND ROW(NEW.organization_id, NEW.form_id, NEW.version, NEW.title,
                   NEW.introduction, NEW.field_schema, NEW.event_type_options,
                   NEW.location_options, NEW.duration_options_minutes, NEW.timezone_name,
                   NEW.responsible_membership_id, NEW.origin, NEW.origin_detail,
                   NEW.attribution, NEW.consent_presentation, NEW.portal_scopes,
                   NEW.acknowledgement_template_version_id, NEW.configuration_sha256,
                   NEW.created_by_membership_id, NEW.published_by_membership_id,
                   NEW.published_at, NEW.created_at)
               IS NOT DISTINCT FROM
               ROW(OLD.organization_id, OLD.form_id, OLD.version, OLD.title,
                   OLD.introduction, OLD.field_schema, OLD.event_type_options,
                   OLD.location_options, OLD.duration_options_minutes, OLD.timezone_name,
                   OLD.responsible_membership_id, OLD.origin, OLD.origin_detail,
                   OLD.attribution, OLD.consent_presentation, OLD.portal_scopes,
                   OLD.acknowledgement_template_version_id, OLD.configuration_sha256,
                   OLD.created_by_membership_id, OLD.published_by_membership_id,
                   OLD.published_at, OLD.created_at) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'published form versions are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER portal_form_version_immutable
BEFORE UPDATE ON portal_publicformversion
FOR EACH ROW EXECUTE FUNCTION portal_guard_form_version_immutable();

CREATE OR REPLACE FUNCTION portal_guard_submission_completion()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'processing'
       AND NEW.state IN ('completed', 'rejected')
       AND NEW.completed_at IS NOT NULL
       AND ROW(NEW.organization_id, NEW.form_version_id, NEW.idempotency_key_hmac,
               NEW.payload_sha256, NEW.evidence_sha256, NEW.attribution_sha256,
               NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.form_version_id, OLD.idempotency_key_hmac,
               OLD.payload_sha256, OLD.evidence_sha256, OLD.attribution_sha256,
               OLD.created_at)
       AND (
           (NEW.state = 'completed'
            AND NEW.person_reference IS NOT NULL
            AND NEW.event_request_reference IS NOT NULL)
           OR
           (NEW.state = 'rejected'
            AND NEW.person_reference IS NULL
            AND NEW.event_request_reference IS NULL
            AND NEW.consent_event_references = '[]'::jsonb)
       ) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'public form submissions only admit one terminal completion'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_submission_completion_guard
BEFORE UPDATE ON portal_publicformsubmission
FOR EACH ROW EXECUTE FUNCTION portal_guard_submission_completion();

CREATE OR REPLACE FUNCTION portal_guard_grant_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.principal_id, NEW.person_reference,
           NEW.event_request_reference, NEW.scopes, NEW.issued_by_membership_id,
           NEW.provenance, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.principal_id, OLD.person_reference,
           OLD.event_request_reference, OLD.scopes, OLD.issued_by_membership_id,
           OLD.provenance, OLD.created_at) THEN
        RAISE EXCEPTION 'portal grant identity, anchor, scopes and provenance are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.state = 'active'
       AND NEW.state = 'active'
       AND OLD.root_reservation_reference IS NULL
       AND NEW.root_reservation_reference IS NOT NULL
       AND NEW.revision = OLD.revision + 1
       AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at
       AND NEW.revoked_by_membership_id IS NOT DISTINCT FROM OLD.revoked_by_membership_id THEN
        RETURN NEW;
    END IF;
    IF OLD.state = 'active'
       AND NEW.state = 'revoked'
       AND NEW.revision = OLD.revision + 1
       AND NEW.root_reservation_reference IS NOT DISTINCT FROM OLD.root_reservation_reference
       AND NEW.revoked_at IS NOT NULL
       AND NEW.revoked_by_membership_id IS NOT NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'portal grant transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_grant_transition_guard
BEFORE UPDATE ON portal_portalgrant
FOR EACH ROW EXECUTE FUNCTION portal_guard_grant_transition();

CREATE OR REPLACE FUNCTION portal_guard_principal_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.organization_id, OLD.created_at) THEN
        RAISE EXCEPTION 'portal principal tenant and creation are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.state = 'active'
       AND NEW.state = 'active'
       AND NEW.revision = OLD.revision + 1
       AND NEW.reconciled_at IS NOT NULL
       AND ROW(NEW.person_reference, NEW.canonical_set)
           IS DISTINCT FROM ROW(OLD.person_reference, OLD.canonical_set) THEN
        RETURN NEW;
    END IF;
    IF OLD.state = 'active'
       AND NEW.state = 'collision'
       AND NEW.revision = OLD.revision + 1
       AND NEW.reconciled_at IS NOT NULL
       AND ROW(NEW.person_reference, NEW.canonical_set)
           IS NOT DISTINCT FROM ROW(OLD.person_reference, OLD.canonical_set) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'portal principal transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_principal_transition_guard
BEFORE UPDATE ON portal_portalprincipal
FOR EACH ROW EXECUTE FUNCTION portal_guard_principal_transition();

CREATE OR REPLACE FUNCTION portal_guard_challenge_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.principal_id, NEW.kind, NEW.channel,
           NEW.contact_fingerprint, NEW.contact_revision, NEW.expires_at,
           NEW.max_attempts, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.principal_id, OLD.kind, OLD.channel,
           OLD.contact_fingerprint, OLD.contact_revision, OLD.expires_at,
           OLD.max_attempts, OLD.created_at)
       OR OLD.consumed_at IS NOT NULL
       OR OLD.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'portal challenge identity or terminal state is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.code_hmac = 'pending'
       AND NEW.code_hmac ~ '^[0-9a-f]{64}$'
       AND ROW(NEW.attempt_count, NEW.consumed_at, NEW.revoked_at)
           IS NOT DISTINCT FROM ROW(OLD.attempt_count, OLD.consumed_at, OLD.revoked_at) THEN
        RETURN NEW;
    END IF;
    IF NEW.code_hmac IS NOT DISTINCT FROM OLD.code_hmac
       AND NEW.attempt_count = OLD.attempt_count + 1
       AND NEW.attempt_count <= NEW.max_attempts
       AND (
           (NEW.consumed_at IS NOT DISTINCT FROM OLD.consumed_at
            AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at)
           OR (OLD.consumed_at IS NULL AND NEW.consumed_at IS NOT NULL
               AND NEW.revoked_at IS NULL)
           OR (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
               AND NEW.consumed_at IS NULL)
       ) THEN
        RETURN NEW;
    END IF;
    IF NEW.code_hmac IS NOT DISTINCT FROM OLD.code_hmac
       AND NEW.attempt_count = OLD.attempt_count
       AND OLD.revoked_at IS NULL
       AND NEW.revoked_at IS NOT NULL
       AND NEW.consumed_at IS NOT DISTINCT FROM OLD.consumed_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'portal challenge transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_challenge_transition_guard
BEFORE UPDATE ON portal_portalchallenge
FOR EACH ROW EXECUTE FUNCTION portal_guard_challenge_transition();

CREATE OR REPLACE FUNCTION portal_guard_session_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.principal_id, NEW.contact_fingerprint,
           NEW.contact_revision, NEW.absolute_expires_at, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.principal_id, OLD.contact_fingerprint,
           OLD.contact_revision, OLD.absolute_expires_at, OLD.created_at)
       OR OLD.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'portal session identity or terminal state is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.token_hmac IS NOT DISTINCT FROM OLD.token_hmac
       AND NEW.rotation = OLD.rotation
       AND NEW.revoked_at IS NULL
       AND NEW.revocation_reason = OLD.revocation_reason
       AND NEW.last_seen_at >= OLD.last_seen_at
       AND NEW.idle_expires_at <= NEW.absolute_expires_at THEN
        RETURN NEW;
    END IF;
    IF NEW.token_hmac IS DISTINCT FROM OLD.token_hmac
       AND NEW.rotation = OLD.rotation + 1
       AND ROW(NEW.idle_expires_at, NEW.last_seen_at, NEW.revoked_at,
               NEW.revocation_reason)
           IS NOT DISTINCT FROM
           ROW(OLD.idle_expires_at, OLD.last_seen_at, OLD.revoked_at,
               OLD.revocation_reason) THEN
        RETURN NEW;
    END IF;
    IF NEW.token_hmac IS NOT DISTINCT FROM OLD.token_hmac
       AND NEW.rotation = OLD.rotation
       AND ROW(NEW.idle_expires_at, NEW.last_seen_at)
           IS NOT DISTINCT FROM ROW(OLD.idle_expires_at, OLD.last_seen_at)
       AND OLD.revoked_at IS NULL
       AND NEW.revoked_at IS NOT NULL
       AND NEW.revocation_reason <> '' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'portal session transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_session_transition_guard
BEFORE UPDATE ON portal_portalsession
FOR EACH ROW EXECUTE FUNCTION portal_guard_session_transition();

CREATE OR REPLACE FUNCTION portal_guard_form_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'active'
       AND NEW.status = 'retired'
       AND ROW(NEW.organization_id, NEW.name, NEW.created_by_membership_id, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.name, OLD.created_by_membership_id, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'public form identity or transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_form_transition_guard
BEFORE UPDATE ON portal_publicform
FOR EACH ROW EXECUTE FUNCTION portal_guard_form_transition();

CREATE OR REPLACE FUNCTION portal_guard_locator_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.revoked_at IS NULL
       AND NEW.revoked_at IS NOT NULL
       AND ROW(NEW.token_hmac, NEW.organization_id, NEW.kind,
               NEW.target_reference, NEW.expires_at, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.token_hmac, OLD.organization_id, OLD.kind,
               OLD.target_reference, OLD.expires_at, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'portal locator identity or transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER portal_locator_transition_guard
BEFORE UPDATE ON portal_portallocator
FOR EACH ROW EXECUTE FUNCTION portal_guard_locator_transition();
"""

REVERSE_INTEGRITY_SQL = r"""
DROP TRIGGER IF EXISTS portal_form_version_immutable
ON portal_publicformversion;
DROP TRIGGER IF EXISTS portal_submission_completion_guard
ON portal_publicformsubmission;
DROP TRIGGER IF EXISTS portal_grant_transition_guard
ON portal_portalgrant;
DROP TRIGGER IF EXISTS portal_principal_transition_guard
ON portal_portalprincipal;
DROP TRIGGER IF EXISTS portal_challenge_transition_guard
ON portal_portalchallenge;
DROP TRIGGER IF EXISTS portal_session_transition_guard
ON portal_portalsession;
DROP TRIGGER IF EXISTS portal_form_transition_guard
ON portal_publicform;
DROP TRIGGER IF EXISTS portal_locator_transition_guard
ON portal_portallocator;

DROP FUNCTION IF EXISTS portal_guard_form_version_immutable();
DROP FUNCTION IF EXISTS portal_guard_submission_completion();
DROP FUNCTION IF EXISTS portal_guard_grant_transition();
DROP FUNCTION IF EXISTS portal_guard_principal_transition();
DROP FUNCTION IF EXISTS portal_guard_challenge_transition();
DROP FUNCTION IF EXISTS portal_guard_session_transition();
DROP FUNCTION IF EXISTS portal_guard_form_transition();
DROP FUNCTION IF EXISTS portal_guard_locator_transition();

ALTER TABLE portal_publicformsubmission
DROP CONSTRAINT IF EXISTS portal_submission_org_formversion_fk;
ALTER TABLE portal_publicformversion
DROP CONSTRAINT IF EXISTS portal_formversion_org_form_fk;
ALTER TABLE portal_portalsession
DROP CONSTRAINT IF EXISTS portal_session_org_principal_fk;
ALTER TABLE portal_portalchallenge
DROP CONSTRAINT IF EXISTS portal_challenge_org_principal_fk;
ALTER TABLE portal_portalgrant
DROP CONSTRAINT IF EXISTS portal_grant_org_principal_fk;
"""


GLOBAL_PRIVILEGES_SQL = r"""
REVOKE ALL ON TABLE portal_portallocator FROM PUBLIC;
REVOKE ALL ON TABLE portal_portallocator FROM claridez_app;
GRANT SELECT, INSERT, UPDATE ON TABLE portal_portallocator TO claridez_app;

REVOKE ALL ON TABLE portal_portalratelimitbucket FROM PUBLIC;
REVOKE ALL ON TABLE portal_portalratelimitbucket FROM claridez_app;
GRANT SELECT, INSERT, UPDATE ON TABLE portal_portalratelimitbucket TO claridez_app;
GRANT USAGE, SELECT ON SEQUENCE portal_portalratelimitbucket_id_seq TO claridez_app;

REVOKE ALL ON TABLE portal_antiabusetokenuse FROM PUBLIC;
REVOKE ALL ON TABLE portal_antiabusetokenuse FROM claridez_app;
GRANT SELECT, INSERT ON TABLE portal_antiabusetokenuse TO claridez_app;
GRANT USAGE, SELECT ON SEQUENCE portal_antiabusetokenuse_id_seq TO claridez_app;
"""

REVERSE_GLOBAL_PRIVILEGES_SQL = r"""
REVOKE ALL ON TABLE portal_portallocator FROM claridez_app;
REVOKE ALL ON TABLE portal_portalratelimitbucket FROM claridez_app;
REVOKE ALL ON SEQUENCE portal_portalratelimitbucket_id_seq FROM claridez_app;
REVOKE ALL ON TABLE portal_antiabusetokenuse FROM claridez_app;
REVOKE ALL ON SEQUENCE portal_antiabusetokenuse_id_seq FROM claridez_app;
"""


class Migration(migrations.Migration):
    dependencies = [("portal", "0001_initial")]
    operations = [
        migrations.RunSQL(INTEGRITY_SQL, reverse_sql=REVERSE_INTEGRITY_SQL),
        migrations.RunSQL(_rls_sql(), reverse_sql=_reverse_rls_sql()),
        migrations.RunSQL(GLOBAL_PRIVILEGES_SQL, reverse_sql=REVERSE_GLOBAL_PRIVILEGES_SQL),
    ]
