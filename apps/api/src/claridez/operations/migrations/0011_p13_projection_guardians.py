# ruff: noqa: E501

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE public.operations_operationalverificationevent
ADD CONSTRAINT op13_vevent_corrects_fk FOREIGN KEY (organization_id, corrects_id)
REFERENCES public.operations_operationalverificationevent (organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION public.claridez_operations_guard_verification_event()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE corrected record; approved_changes integer;
BEGIN
    IF NEW.corrects_id IS NULL THEN
        SELECT count(*) INTO approved_changes
        FROM public.operations_operationalchangedecision decision
        JOIN public.operations_operationalchangeproposal proposal
          ON proposal.organization_id = decision.organization_id
         AND proposal.id = decision.proposal_id
        WHERE decision.organization_id = NEW.organization_id AND decision.approved
          AND proposal.scope = 'verification' AND proposal.target_id = NEW.verification_id;
        IF NEW.from_status <> 'pending'
           OR NEW.verification_revision <> 2 + approved_changes
           OR NEW.correction_reason <> '' THEN
            RAISE EXCEPTION 'verification resolution provenance is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO corrected FROM public.operations_operationalverificationevent
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id;
        IF corrected.id IS NULL OR corrected.verification_id <> NEW.verification_id
           OR NEW.verification_revision <> corrected.verification_revision + 1
           OR NEW.from_status <> corrected.to_status OR NEW.correction_reason = '' THEN
            RAISE EXCEPTION 'verification correction provenance is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_verification_event() FROM PUBLIC;
CREATE TRIGGER operations_verification_event_guard
BEFORE INSERT ON public.operations_operationalverificationevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_verification_event();

CREATE FUNCTION public.claridez_operations_validate_verification_projection()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_organization uuid; target_verification uuid; projection record; latest record;
        definition record; latest_change record; effective_change jsonb;
        approved_changes integer; event_count integer; expected_revision integer;
        previous_context text;
BEGIN
    IF TG_TABLE_NAME = 'operations_operationalverificationevent' THEN
        target_organization := NEW.organization_id;
        target_verification := NEW.verification_id;
    ELSE
        target_organization := coalesce(NEW.organization_id, OLD.organization_id);
        target_verification := coalesce(NEW.id, OLD.id);
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', target_organization::text, true);
    SELECT * INTO projection FROM public.operations_operationalverification
    WHERE organization_id = target_organization AND id = target_verification;
    SELECT * INTO latest FROM public.operations_operationalverificationevent
    WHERE organization_id = target_organization AND verification_id = target_verification
    ORDER BY verification_revision DESC, id DESC LIMIT 1;
    SELECT * INTO definition FROM public.operations_templatephasedefinition
    WHERE organization_id = target_organization AND id = projection.definition_id;
    SELECT count(*) INTO approved_changes
    FROM public.operations_operationalchangedecision decision
    JOIN public.operations_operationalchangeproposal proposal
      ON proposal.organization_id = decision.organization_id
     AND proposal.id = decision.proposal_id
    WHERE decision.organization_id = target_organization AND decision.approved
      AND proposal.scope = 'verification' AND proposal.target_id = target_verification;
    SELECT proposal.* INTO latest_change
    FROM public.operations_operationalchangeproposal proposal
    JOIN public.operations_operationalchangedecision decision
      ON decision.organization_id = proposal.organization_id
     AND decision.proposal_id = proposal.id AND decision.approved
    WHERE proposal.organization_id = target_organization
      AND proposal.scope = 'verification' AND proposal.target_id = target_verification
    ORDER BY decision.decided_at DESC, decision.id DESC LIMIT 1;
    SELECT count(*) INTO event_count FROM public.operations_operationalverificationevent
    WHERE organization_id = target_organization AND verification_id = target_verification;
    expected_revision := 1 + approved_changes + event_count;
    IF latest_change.id IS NULL THEN
        IF definition.id IS NULL OR ROW(projection.title, projection.is_required,
           projection.role_key) IS DISTINCT FROM ROW(definition.title,
           definition.is_required, definition.role_key) THEN
            RAISE EXCEPTION 'verification definition diverges from frozen snapshot'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        effective_change := latest_change.before_payload || latest_change.proposed_payload;
        IF ROW(projection.title, projection.is_required, projection.role_key)
           IS DISTINCT FROM ROW(effective_change ->> 'title',
             (effective_change ->> 'is_required')::boolean,
             effective_change ->> 'role_key') THEN
            RAISE EXCEPTION 'verification projection diverges from authorized change'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF projection.id IS NULL THEN
        RAISE EXCEPTION 'verification projection is missing' USING ERRCODE = '23514';
    ELSIF latest.id IS NULL THEN
        IF projection.status <> 'pending' OR projection.revision <> expected_revision
           OR projection.completed_at IS NOT NULL
           OR projection.completed_by_membership_id IS NOT NULL
           OR projection.status_reason <> '' THEN
            RAISE EXCEPTION 'pending verification projection has no matching ledger'
                USING ERRCODE = '23514';
        END IF;
    ELSIF projection.status <> latest.to_status
       OR projection.revision <> expected_revision
       OR projection.revision <> latest.verification_revision
       OR projection.completed_at <> latest.occurred_at
       OR projection.completed_by_membership_id <> latest.actor_membership_id
       OR projection.status_reason <> latest.reason THEN
        RAISE EXCEPTION 'verification projection diverges from append-only ledger'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_validate_verification_projection() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER operations_verification_projection_complete
AFTER INSERT OR UPDATE OR DELETE ON public.operations_operationalverification
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_verification_projection();
CREATE CONSTRAINT TRIGGER operations_verification_event_complete
AFTER INSERT ON public.operations_operationalverificationevent
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_verification_projection();

CREATE FUNCTION public.claridez_operations_freeze_verification_definition()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF ROW(NEW.organization_id, NEW.preparation_id, NEW.snapshot_id, NEW.definition_id,
           NEW.source_key, NEW.phase, NEW.title, NEW.is_required, NEW.role_key,
           NEW.position, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.preparation_id, OLD.snapshot_id, OLD.definition_id,
           OLD.source_key, OLD.phase, OLD.title, OLD.is_required, OLD.role_key,
           OLD.position, OLD.created_at) THEN
        RAISE EXCEPTION 'fulfilled verification definition is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_freeze_verification_definition() FROM PUBLIC;
CREATE TRIGGER operations_verification_definition_guard
BEFORE UPDATE ON public.operations_operationalverification
FOR EACH ROW WHEN (OLD.status <> 'pending')
EXECUTE FUNCTION public.claridez_operations_freeze_verification_definition();

CREATE FUNCTION public.claridez_operations_guard_incident_event()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE prior record; corrected record;
BEGIN
    SELECT * INTO prior FROM public.operations_operationalincidentevent
    WHERE organization_id = NEW.organization_id AND incident_id = NEW.incident_id
    ORDER BY incident_revision DESC, id DESC LIMIT 1;
    IF NEW.kind = 'opened' THEN
        IF prior.id IS NOT NULL OR NEW.incident_revision <> 1 OR NEW.from_status <> ''
           OR NEW.to_status <> 'open' OR NEW.corrects_id IS NOT NULL THEN
            RAISE EXCEPTION 'incident opening provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF prior.id IS NULL OR NEW.incident_revision <> prior.incident_revision + 1 THEN
        RAISE EXCEPTION 'incident event revision is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'contained' AND NOT (
        prior.to_status = 'open' AND NEW.from_status = 'open'
        AND NEW.to_status = 'contained' AND NEW.corrects_id IS NULL
    ) THEN
        RAISE EXCEPTION 'incident containment transition is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'resolved' AND NOT (
        prior.to_status IN ('open', 'contained') AND NEW.from_status = prior.to_status
        AND NEW.to_status = 'resolved' AND NEW.corrects_id IS NULL
    ) THEN
        RAISE EXCEPTION 'incident resolution transition is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind IN ('reassigned', 'impact_updated') AND NOT (
        NEW.from_status = prior.to_status AND NEW.to_status = prior.to_status
        AND NEW.corrects_id IS NULL
    ) THEN
        RAISE EXCEPTION 'incident amendment provenance is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'corrected' THEN
        SELECT * INTO corrected FROM public.operations_operationalincidentevent
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id;
        IF corrected.id IS NULL OR corrected.incident_id <> NEW.incident_id
           OR NEW.from_status <> prior.to_status OR NEW.to_status <> prior.to_status THEN
            RAISE EXCEPTION 'incident correction provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.kind NOT IN ('contained', 'resolved', 'reassigned', 'impact_updated', 'corrected') THEN
        RAISE EXCEPTION 'incident event kind is invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_incident_event() FROM PUBLIC;
CREATE TRIGGER operations_incident_event_guard
BEFORE INSERT ON public.operations_operationalincidentevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_incident_event();

CREATE FUNCTION public.claridez_operations_validate_incident_projection()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_organization uuid; target_incident uuid; projection record; latest record;
        previous_context text;
BEGIN
    IF TG_TABLE_NAME = 'operations_operationalincidentevent' THEN
        target_organization := NEW.organization_id;
        target_incident := NEW.incident_id;
    ELSE
        target_organization := coalesce(NEW.organization_id, OLD.organization_id);
        target_incident := coalesce(NEW.id, OLD.id);
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', target_organization::text, true);
    SELECT * INTO projection FROM public.operations_operationalincident
    WHERE organization_id = target_organization AND id = target_incident;
    SELECT * INTO latest FROM public.operations_operationalincidentevent
    WHERE organization_id = target_organization AND incident_id = target_incident
    ORDER BY incident_revision DESC, id DESC LIMIT 1;
    IF projection.id IS NULL OR latest.id IS NULL
       OR projection.status <> latest.to_status OR projection.severity <> latest.severity
       OR projection.impact <> latest.impact
       OR projection.responsible_membership_id IS DISTINCT FROM latest.responsible_membership_id
       OR projection.revision <> latest.incident_revision THEN
        RAISE EXCEPTION 'incident projection diverges from append-only ledger'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_validate_incident_projection() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER operations_incident_projection_complete
AFTER INSERT OR UPDATE OR DELETE ON public.operations_operationalincident
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_incident_projection();
CREATE CONSTRAINT TRIGGER operations_incident_event_complete
AFTER INSERT ON public.operations_operationalincidentevent
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_incident_projection();

CREATE FUNCTION public.claridez_operations_freeze_incident_identity()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF ROW(NEW.organization_id, NEW.preparation_id, NEW.incident_type, NEW.description,
           NEW.reported_by_membership_id, NEW.reported_at, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.preparation_id, OLD.incident_type, OLD.description,
           OLD.reported_by_membership_id, OLD.reported_at, OLD.created_at) THEN
        RAISE EXCEPTION 'incident identity is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_freeze_incident_identity() FROM PUBLIC;
CREATE TRIGGER operations_incident_identity_guard
BEFORE UPDATE ON public.operations_operationalincident
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_freeze_incident_identity();

CREATE FUNCTION public.claridez_operations_guard_change_projection()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_organization uuid; target_proposal uuid; proposal record; decision record;
        previous_context text;
BEGIN
    IF TG_TABLE_NAME = 'operations_operationalchangedecision' THEN
        target_organization := NEW.organization_id;
        target_proposal := NEW.proposal_id;
    ELSE
        target_organization := NEW.organization_id;
        target_proposal := NEW.id;
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', target_organization::text, true);
    IF TG_TABLE_NAME = 'operations_operationalchangeproposal' THEN
        IF TG_OP = 'UPDATE' AND ROW(NEW.organization_id, NEW.preparation_id, NEW.scope,
           NEW.target_id, NEW.before_payload, NEW.proposed_payload, NEW.reason, NEW.impact,
           NEW.proposed_by_membership_id, NEW.expected_preparation_revision,
           NEW.idempotency_key, NEW.payload_sha256, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.organization_id, OLD.preparation_id, OLD.scope,
           OLD.target_id, OLD.before_payload, OLD.proposed_payload, OLD.reason, OLD.impact,
           OLD.proposed_by_membership_id, OLD.expected_preparation_revision,
           OLD.idempotency_key, OLD.payload_sha256, OLD.created_at) THEN
            RAISE EXCEPTION 'operational change proposal is immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT * INTO proposal FROM public.operations_operationalchangeproposal
    WHERE organization_id = target_organization AND id = target_proposal;
    SELECT * INTO decision FROM public.operations_operationalchangedecision
    WHERE organization_id = target_organization AND proposal_id = target_proposal;
    IF proposal.status = 'pending' AND decision.id IS NOT NULL THEN
        RAISE EXCEPTION 'pending proposal cannot have decision' USING ERRCODE = '23514';
    ELSIF proposal.status = 'approved' AND (decision.id IS NULL OR NOT decision.approved) THEN
        RAISE EXCEPTION 'approved proposal lacks matching decision' USING ERRCODE = '23514';
    ELSIF proposal.status = 'rejected' AND (decision.id IS NULL OR decision.approved) THEN
        RAISE EXCEPTION 'rejected proposal lacks matching decision' USING ERRCODE = '23514';
    END IF;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_change_projection() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER operations_change_projection_complete
AFTER INSERT OR UPDATE ON public.operations_operationalchangeproposal
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_guard_change_projection();
CREATE CONSTRAINT TRIGGER operations_change_decision_complete
AFTER INSERT ON public.operations_operationalchangedecision
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_guard_change_projection();

CREATE OR REPLACE FUNCTION public.claridez_operations_guard_window()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE preparation record; snapshot record; reservation record; allocation record;
        event record; predecessor_reservation record; need record; decision record;
        proposal record; predecessor_window record;
        effective_change jsonb;
        expected_start timestamptz; expected_end timestamptz;
BEGIN
    SELECT * INTO preparation FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id;
    SELECT * INTO snapshot FROM public.operations_operationalplansnapshot
    WHERE organization_id = NEW.organization_id AND id = NEW.snapshot_id;
    SELECT * INTO reservation FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id;
    SELECT * INTO allocation FROM public.scheduling_scheduleallocation
    WHERE organization_id = NEW.organization_id AND id = NEW.schedule_allocation_id;
    SELECT * INTO event FROM public.scheduling_scheduleevent
    WHERE organization_id = NEW.organization_id AND id = NEW.schedule_event_id;
    SELECT * INTO predecessor_reservation FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = reservation.predecessor_id;
    IF preparation.reservation_id IS NULL OR snapshot.id IS NULL OR reservation.id IS NULL
       OR allocation.id IS NULL OR event.id IS NULL
       OR preparation.status NOT IN ('preparing', 'ready', 'in_progress')
       OR preparation.reservation_id <> reservation.id OR NEW.preparation_id <> reservation.id
       OR NEW.root_reservation_id <> reservation.root_id
       OR snapshot.preparation_id <> preparation.reservation_id
       OR reservation.status <> 'confirmed' OR allocation.reservation_id <> reservation.id
       OR allocation.space_id <> reservation.space_id OR allocation.source_event_id <> event.id
       OR allocation.source_revision <> reservation.revision
       OR NEW.schedule_reservation_revision <> reservation.revision
       OR NEW.schedule_source_revision <> allocation.source_revision
       OR event.event_request_id <> reservation.event_request_id
       OR event.root_reservation_id <> reservation.root_id
       OR NOT (
          (event.kind = 'reservation_confirmed' AND event.reservation_id = reservation.id
             AND event.aggregate_revision = reservation.revision)
          OR (event.kind = 'reservation_rescheduled' AND event.reservation_id = reservation.id
             AND event.successor_id = reservation.id
             AND event.predecessor_id = reservation.predecessor_id
             AND predecessor_reservation.id = reservation.predecessor_id
             AND predecessor_reservation.root_id = reservation.root_id
             AND predecessor_reservation.event_request_id = reservation.event_request_id
             AND predecessor_reservation.status = 'rescheduled'
             AND event.aggregate_revision = predecessor_reservation.revision
             AND (event.new_snapshot ->> 'revision')::integer = reservation.revision)
          OR (event.kind = 'cutover_snapshot' AND event.reservation_id = reservation.id
             AND event.aggregate_revision = reservation.revision)
       )
       OR NOT (NEW.required_interval <@ allocation.occupied_interval)
    THEN
        RAISE EXCEPTION 'operational window diverges from scheduling authority'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_kind = 'organization_template' THEN
        SELECT * INTO need FROM public.operations_templateresourceneed
        WHERE organization_id = NEW.organization_id AND id = NEW.resource_need_id;
        IF preparation.status NOT IN ('preparing', 'ready')
           OR need.id IS NULL OR snapshot.source_kind <> 'organization'
           OR snapshot.template_version_id <> need.version_id
           OR NEW.resource_id <> need.resource_id OR NEW.quantity <> need.quantity
           OR NEW.source_version <> snapshot.source_version
           OR NEW.window_revision <> 1 OR NEW.predecessor_id IS NOT NULL THEN
            RAISE EXCEPTION 'template operational window provenance is invalid'
                USING ERRCODE = '23514';
        END IF;
        expected_start := CASE need.start_anchor
            WHEN 'occupied_start' THEN lower(allocation.occupied_interval)
            WHEN 'event_start' THEN lower(reservation.event_interval)
            WHEN 'event_end' THEN upper(reservation.event_interval)
            ELSE upper(allocation.occupied_interval) END
            + make_interval(mins => need.start_offset_minutes);
        expected_end := CASE need.end_anchor
            WHEN 'occupied_start' THEN lower(allocation.occupied_interval)
            WHEN 'event_start' THEN lower(reservation.event_interval)
            WHEN 'event_end' THEN upper(reservation.event_interval)
            ELSE upper(allocation.occupied_interval) END
            + make_interval(mins => need.end_offset_minutes);
        IF NEW.required_interval <> tstzrange(expected_start, expected_end, '[)') THEN
            RAISE EXCEPTION 'template operational window interval is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.source_kind = 'authorized_change' THEN
        SELECT decision.* INTO decision
        FROM public.operations_operationalchangedecision decision
        WHERE decision.organization_id = NEW.organization_id
          AND decision.id = NEW.authorization_decision_id;
        SELECT * INTO proposal FROM public.operations_operationalchangeproposal
        WHERE organization_id = NEW.organization_id AND id = decision.proposal_id;
        SELECT * INTO predecessor_window FROM public.operations_operationalresourcewindow
        WHERE organization_id = NEW.organization_id AND id = NEW.predecessor_id;
        IF decision.id IS NULL OR NOT decision.approved
           OR proposal.preparation_id <> NEW.preparation_id
           OR NEW.resource_need_id IS NOT NULL
           OR NEW.source_version <> snapshot.source_version || ':change:' || decision.id::text
           OR NOT (
               (proposal.scope = 'resource_window'
                AND proposal.target_id = NEW.predecessor_id
                AND predecessor_window.id IS NOT NULL
                AND predecessor_window.preparation_id = NEW.preparation_id
                AND NEW.window_revision = predecessor_window.window_revision + 1)
               OR
               (proposal.scope = 'resource_need'
                AND proposal.target_id = NEW.snapshot_id
                AND NEW.predecessor_id IS NULL
                AND NEW.window_revision = 1)
           ) THEN
            RAISE EXCEPTION 'authorized operational window provenance is invalid'
                USING ERRCODE = '23514';
        END IF;
        effective_change := proposal.before_payload || proposal.proposed_payload;
        expected_start := CASE effective_change ->> 'start_anchor'
            WHEN 'occupied_start' THEN lower(allocation.occupied_interval)
            WHEN 'event_start' THEN lower(reservation.event_interval)
            WHEN 'event_end' THEN upper(reservation.event_interval)
            WHEN 'occupied_end' THEN upper(allocation.occupied_interval)
            ELSE NULL END + make_interval(
                mins => (effective_change ->> 'start_offset_minutes')::integer
            );
        expected_end := CASE effective_change ->> 'end_anchor'
            WHEN 'occupied_start' THEN lower(allocation.occupied_interval)
            WHEN 'event_start' THEN lower(reservation.event_interval)
            WHEN 'event_end' THEN upper(reservation.event_interval)
            WHEN 'occupied_end' THEN upper(allocation.occupied_interval)
            ELSE NULL END + make_interval(
                mins => (effective_change ->> 'end_offset_minutes')::integer
            );
        IF expected_start IS NULL OR expected_end IS NULL
           OR NEW.resource_id <> (effective_change ->> 'resource_id')::uuid
           OR NEW.quantity <> (effective_change ->> 'quantity')::numeric
           OR NEW.required_interval <> tstzrange(expected_start, expected_end, '[)') THEN
            RAISE EXCEPTION 'authorized operational window projection is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'system fallback cannot invent resource windows'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS operations_change_decision_complete ON public.operations_operationalchangedecision;
DROP TRIGGER IF EXISTS operations_change_projection_complete ON public.operations_operationalchangeproposal;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_change_projection();
DROP TRIGGER IF EXISTS operations_incident_identity_guard ON public.operations_operationalincident;
DROP FUNCTION IF EXISTS public.claridez_operations_freeze_incident_identity();
DROP TRIGGER IF EXISTS operations_incident_event_complete ON public.operations_operationalincidentevent;
DROP TRIGGER IF EXISTS operations_incident_projection_complete ON public.operations_operationalincident;
DROP FUNCTION IF EXISTS public.claridez_operations_validate_incident_projection();
DROP TRIGGER IF EXISTS operations_incident_event_guard ON public.operations_operationalincidentevent;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_incident_event();
DROP TRIGGER IF EXISTS operations_verification_definition_guard ON public.operations_operationalverification;
DROP FUNCTION IF EXISTS public.claridez_operations_freeze_verification_definition();
DROP TRIGGER IF EXISTS operations_verification_event_complete ON public.operations_operationalverificationevent;
DROP TRIGGER IF EXISTS operations_verification_projection_complete ON public.operations_operationalverification;
DROP FUNCTION IF EXISTS public.claridez_operations_validate_verification_projection();
DROP TRIGGER IF EXISTS operations_verification_event_guard ON public.operations_operationalverificationevent;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_verification_event();
ALTER TABLE public.operations_operationalverificationevent DROP CONSTRAINT IF EXISTS op13_vevent_corrects_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0010_alter_operationalincidentevent_corrects")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
