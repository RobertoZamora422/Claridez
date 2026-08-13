from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_guard_document_state_v3()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF TG_TABLE_NAME = 'documents_documenttemplate' THEN
        IF ROW(NEW.organization_id, NEW.name, NEW.kind, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.name, OLD.kind, OLD.created_at) OR
           (NEW.is_active IS DISTINCT FROM OLD.is_active AND NEW.revision <> OLD.revision + 1) OR
           (NEW.is_active IS NOT DISTINCT FROM OLD.is_active AND NEW.revision <> OLD.revision) THEN
            RAISE EXCEPTION 'template identity or revision is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_contractualinstrument' THEN
        IF ROW(NEW.organization_id, NEW.record_id, NEW.instrument_type, NEW.title,
               NEW.created_by_membership_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.record_id, OLD.instrument_type, OLD.title,
               OLD.created_by_membership_id, OLD.created_at) OR
           (NEW.status IS DISTINCT FROM OLD.status AND NEW.revision <> OLD.revision + 1) OR
           (NEW.status IS NOT DISTINCT FROM OLD.status AND NEW.revision <> OLD.revision) THEN
            RAISE EXCEPTION 'instrument identity or revision is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_issuedinstrumentversion' THEN
        IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
            (OLD.state = 'pending_render' AND NEW.state IN ('rendering', 'render_failed')) OR
            (OLD.state = 'rendering' AND NEW.state IN ('issued', 'render_failed'))
        ) THEN
            RAISE EXCEPTION 'invalid issued version transition' USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'issued' AND NEW.issued_at IS NULL THEN
            RAISE EXCEPTION 'issued version requires timestamp' USING ERRCODE = '23514';
        END IF;
        IF OLD.issued_at IS NOT NULL AND NEW.issued_at IS DISTINCT FROM OLD.issued_at THEN
            RAISE EXCEPTION 'issued timestamp is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_generatedartifact' THEN
        IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
            OLD.state = 'available' AND NEW.state = 'integrity_failed'
        ) THEN
            RAISE EXCEPTION 'invalid artifact transition' USING ERRCODE = '23514';
        END IF;
        IF OLD.state = 'integrity_failed' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'failed artifacts are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_externalaccessgrant' THEN
        IF ROW(NEW.organization_id, NEW.issued_version_id, NEW.artifact_id, NEW.purpose,
               NEW.token_hmac, NEW.expires_at, NEW.max_exchanges,
               NEW.created_by_membership_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.issued_version_id, OLD.artifact_id,
               OLD.purpose, OLD.token_hmac, OLD.expires_at, OLD.max_exchanges,
               OLD.created_by_membership_id, OLD.created_at) OR
           NEW.exchange_count < OLD.exchange_count OR NEW.exchange_count > OLD.exchange_count + 1 OR
           (OLD.revoked_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) OR
           ((NEW.revoked_at IS NULL) <> (NEW.revoked_by_membership_id IS NULL)) THEN
            RAISE EXCEPTION 'grant identity or transition is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_externaldocumentsession' THEN
        IF ROW(NEW.organization_id, NEW.grant_id, NEW.token_hmac, NEW.expires_at, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.grant_id, OLD.token_hmac,
               OLD.expires_at, OLD.created_at) OR
           NEW.last_seen_at < OLD.last_seen_at OR
           (OLD.revoked_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
            RAISE EXCEPTION 'external session identity or transition is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_retentionpolicy' THEN
        IF ROW(NEW.organization_id, NEW.key, NEW.version, NEW.name, NEW.classification,
               NEW.rules, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.key, OLD.version, OLD.name,
               OLD.classification, OLD.rules, OLD.created_at) OR
           (NEW.status IS DISTINCT FROM OLD.status AND NOT (
               (OLD.status = 'draft' AND NEW.status = 'active') OR
               (OLD.status = 'active' AND NEW.status = 'retired')
           )) OR
           (OLD.status <> 'draft' AND NEW IS DISTINCT FROM OLD) OR
           ((NEW.status = 'active') AND
            (NEW.approved_at IS NULL OR NEW.approved_by_membership_id IS NULL)) THEN
            RAISE EXCEPTION 'retention policy identity or transition is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_retentionassignment' THEN
        IF ROW(NEW.organization_id, NEW.policy_id, NEW.target_type, NEW.target_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.policy_id, OLD.target_type,
               OLD.target_id, OLD.created_at) THEN
            RAISE EXCEPTION 'retention assignment identity is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_legalhold' THEN
        IF ROW(NEW.organization_id, NEW.assignment_id, NEW.reason, NEW.placed_at,
               NEW.placed_by_membership_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.assignment_id, OLD.reason,
               OLD.placed_at, OLD.placed_by_membership_id, OLD.created_at) OR
           (OLD.released_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) OR
           ((NEW.released_at IS NULL) <> (NEW.released_by_membership_id IS NULL)) OR
           (NEW.released_at IS NOT NULL AND NEW.release_reason = '') THEN
            RAISE EXCEPTION 'legal hold identity or release is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'documents_documentjob' THEN
        IF ROW(NEW.organization_id, NEW.job_type, NEW.target_id, NEW.payload,
               NEW.idempotency_key, NEW.correlation_id, NEW.max_attempts, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.job_type, OLD.target_id, OLD.payload,
               OLD.idempotency_key, OLD.correlation_id, OLD.max_attempts, OLD.created_at) OR
           (OLD.state IN ('succeeded', 'dead') AND NEW IS DISTINCT FROM OLD) OR
           (NEW.state IS DISTINCT FROM OLD.state AND NOT (
               (OLD.state IN ('queued', 'retry_wait') AND NEW.state = 'running') OR
               (OLD.state = 'running' AND NEW.state IN ('retry_wait', 'succeeded', 'dead'))
           )) OR
           (NEW.attempts <> OLD.attempts AND NOT (
               NEW.state = 'running' AND NEW.attempts = OLD.attempts + 1
           )) THEN
            RAISE EXCEPTION 'job identity or transition is invalid' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_document_state_v3() FROM PUBLIC;

CREATE TRIGGER documents_documenttemplate_state_guard BEFORE UPDATE
    ON public.documents_documenttemplate FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_contractualinstrument_state_guard BEFORE UPDATE
    ON public.documents_contractualinstrument FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_issuedinstrumentversion_state_guard BEFORE UPDATE
    ON public.documents_issuedinstrumentversion FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_generatedartifact_state_guard BEFORE UPDATE
    ON public.documents_generatedartifact FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_externalaccessgrant_state_guard BEFORE UPDATE
    ON public.documents_externalaccessgrant FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_externaldocumentsession_state_guard BEFORE UPDATE
    ON public.documents_externaldocumentsession FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_retentionpolicy_state_guard BEFORE UPDATE
    ON public.documents_retentionpolicy FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_retentionassignment_state_guard BEFORE UPDATE
    ON public.documents_retentionassignment FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_legalhold_state_guard BEFORE UPDATE
    ON public.documents_legalhold FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
CREATE TRIGGER documents_documentjob_state_guard BEFORE UPDATE
    ON public.documents_documentjob FOR EACH ROW
    EXECUTE FUNCTION public.claridez_guard_document_state_v3();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS documents_documenttemplate_state_guard ON public.documents_documenttemplate;
DROP TRIGGER IF EXISTS documents_contractualinstrument_state_guard
    ON public.documents_contractualinstrument;
DROP TRIGGER IF EXISTS documents_issuedinstrumentversion_state_guard
    ON public.documents_issuedinstrumentversion;
DROP TRIGGER IF EXISTS documents_generatedartifact_state_guard
    ON public.documents_generatedartifact;
DROP TRIGGER IF EXISTS documents_externalaccessgrant_state_guard
    ON public.documents_externalaccessgrant;
DROP TRIGGER IF EXISTS documents_externaldocumentsession_state_guard
    ON public.documents_externaldocumentsession;
DROP TRIGGER IF EXISTS documents_retentionpolicy_state_guard ON public.documents_retentionpolicy;
DROP TRIGGER IF EXISTS documents_retentionassignment_state_guard
    ON public.documents_retentionassignment;
DROP TRIGGER IF EXISTS documents_legalhold_state_guard ON public.documents_legalhold;
DROP TRIGGER IF EXISTS documents_documentjob_state_guard ON public.documents_documentjob;
DROP FUNCTION IF EXISTS public.claridez_guard_document_state_v3();
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0005_alter_documentjob_job_type")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
