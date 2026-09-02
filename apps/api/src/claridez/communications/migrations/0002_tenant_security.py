# ruff: noqa: E501

from django.db import migrations

PRIVATE_TABLES = (
    "communications_communicationauditevent",
    "communications_communicationintent",
    "communications_communicationoutbox",
    "communications_communicationtemplate",
    "communications_communicationtemplateversion",
    "communications_logicalmessage",
    "communications_deliveryattempt",
    "communications_providerevent",
    "communications_senderidentity",
    "communications_communicationpolicy",
    "communications_communicationpreferenceevent",
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
    append_only = {
        "communications_communicationauditevent",
        "communications_communicationpreferenceevent",
    }
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
ALTER TABLE communications_communicationtemplateversion
ADD CONSTRAINT communications_templateversion_org_template_fk
FOREIGN KEY (organization_id, template_id)
REFERENCES communications_communicationtemplate(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_communicationintent
ADD CONSTRAINT communications_intent_org_templateversion_fk
FOREIGN KEY (organization_id, template_version_id)
REFERENCES communications_communicationtemplateversion(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_logicalmessage
ADD CONSTRAINT communications_message_org_intent_fk
FOREIGN KEY (organization_id, intent_id)
REFERENCES communications_communicationintent(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_logicalmessage
ADD CONSTRAINT communications_message_org_templateversion_fk
FOREIGN KEY (organization_id, template_version_id)
REFERENCES communications_communicationtemplateversion(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_communicationoutbox
ADD CONSTRAINT communications_outbox_org_intent_fk
FOREIGN KEY (organization_id, intent_id)
REFERENCES communications_communicationintent(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_deliveryattempt
ADD CONSTRAINT communications_attempt_org_message_fk
FOREIGN KEY (organization_id, message_id)
REFERENCES communications_logicalmessage(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION communications_guard_preference_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'communication preference history is append-only';
END;
$$;

CREATE TRIGGER communications_preference_append_only
BEFORE UPDATE OR DELETE ON communications_communicationpreferenceevent
FOR EACH ROW EXECUTE FUNCTION communications_guard_preference_append_only();

CREATE OR REPLACE FUNCTION communications_guard_template_version_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('published', 'retired') OR OLD.first_used_at IS NOT NULL THEN
        IF OLD.first_used_at IS NULL AND NEW.first_used_at IS NOT NULL
           AND ROW(NEW.organization_id, NEW.template_id, NEW.version, NEW.status,
                   NEW.subject_template, NEW.body_template, NEW.variable_names,
                   NEW.content_sha256, NEW.published_at, NEW.published_by_membership_id,
                   NEW.created_at)
               IS NOT DISTINCT FROM
               ROW(OLD.organization_id, OLD.template_id, OLD.version, OLD.status,
                   OLD.subject_template, OLD.body_template, OLD.variable_names,
                   OLD.content_sha256, OLD.published_at, OLD.published_by_membership_id,
                   OLD.created_at) THEN
            RETURN NEW;
        END IF;
        IF OLD.status = 'published' AND NEW.status = 'retired'
           AND ROW(NEW.organization_id, NEW.template_id, NEW.version,
                   NEW.subject_template, NEW.body_template, NEW.variable_names,
                   NEW.content_sha256, NEW.published_at, NEW.published_by_membership_id,
                   NEW.first_used_at, NEW.created_at)
               IS NOT DISTINCT FROM
               ROW(OLD.organization_id, OLD.template_id, OLD.version,
                   OLD.subject_template, OLD.body_template, OLD.variable_names,
                   OLD.content_sha256, OLD.published_at, OLD.published_by_membership_id,
                   OLD.first_used_at, OLD.created_at) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'published or used communication template versions are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER communications_template_version_immutable
BEFORE UPDATE ON communications_communicationtemplateversion
FOR EACH ROW EXECUTE FUNCTION communications_guard_template_version_immutable();

CREATE OR REPLACE FUNCTION communications_guard_intent_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.purpose, NEW.channel, NEW.recipient_person_id,
           NEW.template_version_id, NEW.aggregate_type, NEW.aggregate_id, NEW.variables,
           NEW.payload_sha256, NEW.idempotency_key, NEW.source_version, NEW.causal_key,
           NEW.causal_sequence, NEW.not_before, NEW.requested_by_membership_id,
           NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.purpose, OLD.channel, OLD.recipient_person_id,
           OLD.template_version_id, OLD.aggregate_type, OLD.aggregate_id, OLD.variables,
           OLD.payload_sha256, OLD.idempotency_key, OLD.source_version, OLD.causal_key,
           OLD.causal_sequence, OLD.not_before, OLD.requested_by_membership_id,
           OLD.created_at)
       OR OLD.state IN ('cancelled', 'superseded')
       OR NOT (
           (OLD.state = 'pending' AND NEW.state IN ('materialized', 'cancelled', 'superseded', 'terminal'))
           OR (OLD.state = 'materialized' AND NEW.state IN ('cancelled', 'superseded', 'terminal'))
           OR (OLD.state = 'terminal' AND NEW.state = 'pending' AND EXISTS (
               SELECT 1
               FROM communications_communicationoutbox outbox
               WHERE outbox.organization_id = OLD.organization_id
                 AND outbox.intent_id = OLD.id
                 AND outbox.state = 'dead'
           ))
       ) THEN
        RAISE EXCEPTION 'communication intent identity or transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER communications_intent_transition_guard
BEFORE UPDATE ON communications_communicationintent
FOR EACH ROW EXECUTE FUNCTION communications_guard_intent_transition();

CREATE OR REPLACE FUNCTION communications_guard_message_transport_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.intent_id, NEW.template_version_id, NEW.channel,
           NEW.recipient_fingerprint, NEW.resolved_variables, NEW.template_sha256,
           NEW.final_sha256, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.intent_id, OLD.template_version_id, OLD.channel,
           OLD.recipient_fingerprint, OLD.resolved_variables, OLD.template_sha256,
           OLD.final_sha256, OLD.created_at)
       OR OLD.status IN ('suppressed', 'cancelled') THEN
        RAISE EXCEPTION 'logical message content is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.provider_message_id <> ''
       AND ROW(NEW.provider, NEW.provider_message_id)
           IS DISTINCT FROM ROW(OLD.provider, OLD.provider_message_id) THEN
        RAISE EXCEPTION 'provider message identity is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER communications_message_transport_update_guard
BEFORE UPDATE ON communications_logicalmessage
FOR EACH ROW EXECUTE FUNCTION communications_guard_message_transport_update();

CREATE OR REPLACE FUNCTION communications_guard_outbox_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.organization_id, NEW.intent_id, NEW.max_attempts, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.organization_id, OLD.intent_id, OLD.max_attempts, OLD.created_at)
       OR (OLD.message_id IS NOT NULL AND NEW.message_id IS DISTINCT FROM OLD.message_id)
       OR OLD.state IN ('succeeded', 'cancelled')
       OR (NEW.attempt_count <> OLD.attempt_count AND NOT (
           NEW.state = 'claimed' AND NEW.attempt_count = OLD.attempt_count + 1
       ))
       OR (NEW.state IS DISTINCT FROM OLD.state AND NOT (
           (OLD.state IN ('pending', 'retry') AND NEW.state IN ('claimed', 'cancelled'))
           OR (OLD.state = 'claimed' AND NEW.state IN ('claimed', 'retry', 'succeeded', 'dead', 'cancelled'))
           OR (OLD.state = 'dead' AND NEW.state = 'retry')
       )) THEN
        RAISE EXCEPTION 'communication outbox identity or transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER communications_outbox_transition_guard
BEFORE UPDATE ON communications_communicationoutbox
FOR EACH ROW EXECUTE FUNCTION communications_guard_outbox_transition();

CREATE OR REPLACE FUNCTION communications_guard_attempt_completion()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.outcome = 'started'
       AND NEW.outcome IN ('accepted', 'failed')
       AND OLD.finished_at IS NULL
       AND NEW.finished_at IS NOT NULL
       AND ROW(NEW.organization_id, NEW.message_id, NEW.outbox_id, NEW.attempt,
               NEW.provider, NEW.provider_idempotency_key, NEW.started_at, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.message_id, OLD.outbox_id, OLD.attempt,
               OLD.provider, OLD.provider_idempotency_key, OLD.started_at, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'delivery attempts only admit one terminal completion';
END;
$$;

CREATE TRIGGER communications_attempt_completion_guard
BEFORE UPDATE ON communications_deliveryattempt
FOR EACH ROW EXECUTE FUNCTION communications_guard_attempt_completion();

CREATE OR REPLACE FUNCTION communications_guard_provider_event_reconciliation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'recorded'
       AND NEW.state IN ('applied', 'ignored')
       AND ROW(NEW.organization_id, NEW.provider, NEW.provider_account,
               NEW.provider_event_id, NEW.event_type, NEW.external_message_id,
               NEW.message_id,
               NEW.occurred_at, NEW.received_at, NEW.signature_timestamp,
               NEW.payload_sha256, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.provider, OLD.provider_account,
               OLD.provider_event_id, OLD.event_type, OLD.external_message_id,
               OLD.message_id,
               OLD.occurred_at, OLD.received_at, OLD.signature_timestamp,
               OLD.payload_sha256, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'provider events only admit one reconciliation';
END;
$$;

CREATE TRIGGER communications_provider_event_reconciliation_guard
BEFORE UPDATE ON communications_providerevent
FOR EACH ROW EXECUTE FUNCTION communications_guard_provider_event_reconciliation();

CREATE OR REPLACE FUNCTION communications_guard_template_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_active
       AND NOT NEW.is_active
       AND ROW(NEW.organization_id, NEW.name, NEW.channel, NEW.purpose,
               NEW.created_by_membership_id, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.name, OLD.channel, OLD.purpose,
               OLD.created_by_membership_id, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'communication template identity or transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER communications_template_transition_guard
BEFORE UPDATE ON communications_communicationtemplate
FOR EACH ROW EXECUTE FUNCTION communications_guard_template_transition();

CREATE OR REPLACE FUNCTION communications_guard_policy_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'approved'
       AND NEW.status = 'disabled'
       AND ROW(NEW.organization_id, NEW.purpose, NEW.channel, NEW.version,
               NEW.requires_consent, NEW.allow_unsubscribe, NEW.rationale,
               NEW.approved_by_membership_id, NEW.approved_at, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.purpose, OLD.channel, OLD.version,
               OLD.requires_consent, OLD.allow_unsubscribe, OLD.rationale,
               OLD.approved_by_membership_id, OLD.approved_at, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'communication policy versions are immutable'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER communications_policy_transition_guard
BEFORE UPDATE ON communications_communicationpolicy
FOR EACH ROW EXECUTE FUNCTION communications_guard_policy_transition();

CREATE OR REPLACE FUNCTION communications_guard_sender_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_active
       AND NOT NEW.is_active
       AND ROW(NEW.organization_id, NEW.channel, NEW.provider, NEW.ownership,
               NEW.sender_reference, NEW.display_name, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.organization_id, OLD.channel, OLD.provider, OLD.ownership,
               OLD.sender_reference, OLD.display_name, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'sender identity or transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER communications_sender_transition_guard
BEFORE UPDATE ON communications_senderidentity
FOR EACH ROW EXECUTE FUNCTION communications_guard_sender_transition();
"""

REVERSE_INTEGRITY_SQL = r"""
DROP TRIGGER IF EXISTS communications_preference_append_only
ON communications_communicationpreferenceevent;
DROP TRIGGER IF EXISTS communications_template_version_immutable
ON communications_communicationtemplateversion;
DROP TRIGGER IF EXISTS communications_intent_transition_guard
ON communications_communicationintent;
DROP TRIGGER IF EXISTS communications_message_transport_update_guard
ON communications_logicalmessage;
DROP TRIGGER IF EXISTS communications_outbox_transition_guard
ON communications_communicationoutbox;
DROP TRIGGER IF EXISTS communications_attempt_completion_guard
ON communications_deliveryattempt;
DROP TRIGGER IF EXISTS communications_provider_event_reconciliation_guard
ON communications_providerevent;
DROP TRIGGER IF EXISTS communications_template_transition_guard
ON communications_communicationtemplate;
DROP TRIGGER IF EXISTS communications_policy_transition_guard
ON communications_communicationpolicy;
DROP TRIGGER IF EXISTS communications_sender_transition_guard
ON communications_senderidentity;

DROP FUNCTION IF EXISTS communications_guard_preference_append_only();
DROP FUNCTION IF EXISTS communications_guard_template_version_immutable();
DROP FUNCTION IF EXISTS communications_guard_intent_transition();
DROP FUNCTION IF EXISTS communications_guard_message_transport_update();
DROP FUNCTION IF EXISTS communications_guard_outbox_transition();
DROP FUNCTION IF EXISTS communications_guard_attempt_completion();
DROP FUNCTION IF EXISTS communications_guard_provider_event_reconciliation();
DROP FUNCTION IF EXISTS communications_guard_template_transition();
DROP FUNCTION IF EXISTS communications_guard_policy_transition();
DROP FUNCTION IF EXISTS communications_guard_sender_transition();

ALTER TABLE communications_deliveryattempt
DROP CONSTRAINT IF EXISTS communications_attempt_org_message_fk;
ALTER TABLE communications_communicationoutbox
DROP CONSTRAINT IF EXISTS communications_outbox_org_intent_fk;
ALTER TABLE communications_logicalmessage
DROP CONSTRAINT IF EXISTS communications_message_org_templateversion_fk;
ALTER TABLE communications_logicalmessage
DROP CONSTRAINT IF EXISTS communications_message_org_intent_fk;
ALTER TABLE communications_communicationintent
DROP CONSTRAINT IF EXISTS communications_intent_org_templateversion_fk;
ALTER TABLE communications_communicationtemplateversion
DROP CONSTRAINT IF EXISTS communications_templateversion_org_template_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("communications", "0001_initial")]
    operations = [
        migrations.RunSQL(INTEGRITY_SQL, reverse_sql=REVERSE_INTEGRITY_SQL),
        migrations.RunSQL(_rls_sql(), reverse_sql=_reverse_rls_sql()),
    ]
