from django.db import migrations

CUTOVER_SQL = r"""
LOCK TABLE public.commercial_reservation IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE public.commercial_reservation ALTER COLUMN root_id SET NOT NULL;

DO $cutover$
DECLARE
    target_organization uuid;
BEGIN
    FOR target_organization IN
        SELECT id FROM public.organizations_organization ORDER BY id
    LOOP
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', target_organization::text, true
        );

        IF EXISTS (
            SELECT 1
            FROM public.commercial_reservation AS reservation
            LEFT JOIN public.commercial_quotationversion AS version
              ON version.organization_id = reservation.organization_id
             AND version.id = reservation.quotation_version_id
            LEFT JOIN public.commercial_quotation AS quotation
              ON quotation.organization_id = version.organization_id
             AND quotation.id = version.quotation_id
            WHERE reservation.organization_id = target_organization
              AND (
                  version.id IS NULL OR version.status <> 'accepted'
                  OR quotation.event_request_id <> reservation.event_request_id
                  OR reservation.root_id <> reservation.id
                  OR reservation.predecessor_id IS NOT NULL
                  OR reservation.revision <> 1
              )
        ) THEN
            RAISE EXCEPTION 'P8 preflight: reservation commercial evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;

        INSERT INTO public.scheduling_scheduleevent (
            id, organization_id, kind, source, actor_membership_id, reason,
            event_request_id, root_reservation_id, reservation_id,
            predecessor_id, successor_id, block_id, aggregate_revision,
            previous_snapshot, new_snapshot, idempotency_key, payload_hash,
            occurred_at, recorded_at
        )
        SELECT
            md5(reservation.id::text || ':p8:expired')::uuid,
            reservation.organization_id,
            'reservation_expired', 'database_expiration', NULL, '',
            reservation.event_request_id, reservation.root_id, reservation.id,
            NULL, NULL, NULL, reservation.revision + 1,
            jsonb_build_object('status', 'provisional', 'revision', reservation.revision),
            jsonb_build_object('status', 'expired', 'revision', reservation.revision + 1),
            md5(reservation.id::text || ':p8:expired:key')::uuid,
            md5(reservation.id::text || ':p8:expired:payload') ||
                md5('claridez:' || reservation.id::text || ':p8:expired:payload'),
            transaction_timestamp(), transaction_timestamp()
        FROM public.commercial_reservation AS reservation
        WHERE reservation.organization_id = target_organization
          AND reservation.status = 'provisional'
          AND reservation.hold_expires_at <= transaction_timestamp();

        UPDATE public.commercial_reservation
        SET status = 'expired', revision = revision + 1, updated_at = transaction_timestamp()
        WHERE organization_id = target_organization
          AND status = 'provisional'
          AND hold_expires_at <= transaction_timestamp();

        INSERT INTO public.scheduling_scheduleevent (
            id, organization_id, kind, source, actor_membership_id, reason,
            event_request_id, root_reservation_id, reservation_id,
            predecessor_id, successor_id, block_id, aggregate_revision,
            previous_snapshot, new_snapshot, idempotency_key, payload_hash,
            occurred_at, recorded_at
        )
        SELECT
            md5(reservation.id::text || ':p8:cutover')::uuid,
            reservation.organization_id,
            'cutover_snapshot', 'cutover', NULL, '',
            reservation.event_request_id, reservation.id, reservation.id,
            NULL, NULL, NULL, reservation.revision,
            '{}'::jsonb,
            jsonb_build_object(
                'reservation_id', reservation.id::text,
                'root_id', reservation.id::text,
                'space_id', reservation.space_id::text,
                'starts_at', lower(reservation.event_interval),
                'ends_at', upper(reservation.event_interval),
                'timezone', reservation.event_timezone,
                'status', reservation.status,
                'revision', reservation.revision,
                'setup_minutes', 0,
                'teardown_minutes', 0,
                'buffer_before_minutes', 0,
                'buffer_after_minutes', 0,
                'provenance', 'p8_cutover_observed'
            ),
            md5(reservation.id::text || ':p8:cutover:key')::uuid,
            md5(reservation.id::text || ':p8:cutover:payload') ||
                md5('claridez:' || reservation.id::text || ':p8:cutover:payload'),
            transaction_timestamp(), transaction_timestamp()
        FROM public.commercial_reservation AS reservation
        WHERE reservation.organization_id = target_organization
        ON CONFLICT DO NOTHING;

        UPDATE public.commercial_eventrequest AS request
        SET status = 'quoted', updated_at = transaction_timestamp()
        WHERE request.organization_id = target_organization
          AND request.status = 'accepted'
          AND NOT EXISTS (
              SELECT 1 FROM public.commercial_reservation AS reservation
              WHERE reservation.organization_id = request.organization_id
                AND reservation.event_request_id = request.id
                AND reservation.status IN ('provisional', 'confirmed')
          );

        INSERT INTO public.scheduling_scheduleallocation (
            id, organization_id, space_id, reservation_id, block_target_id,
            occupied_interval, source_revision, source_event_id, is_blocking,
            created_at, updated_at
        )
        SELECT
            md5(reservation.id::text || ':p8:allocation')::uuid,
            reservation.organization_id, reservation.space_id, reservation.id, NULL,
            tstzrange(
                lower(reservation.event_interval)
                    - make_interval(mins => reservation.setup_minutes
                        + reservation.buffer_before_minutes),
                upper(reservation.event_interval)
                    + make_interval(mins => reservation.teardown_minutes
                        + reservation.buffer_after_minutes),
                '[)'
            ),
            reservation.revision,
            coalesce(expired_event.id, cutover_event.id),
            reservation.status IN ('provisional', 'confirmed'),
            transaction_timestamp(), transaction_timestamp()
        FROM public.commercial_reservation AS reservation
        JOIN public.scheduling_scheduleevent AS cutover_event
          ON cutover_event.organization_id = reservation.organization_id
         AND cutover_event.reservation_id = reservation.id
         AND cutover_event.kind = 'cutover_snapshot'
        LEFT JOIN public.scheduling_scheduleevent AS expired_event
          ON expired_event.organization_id = reservation.organization_id
         AND expired_event.reservation_id = reservation.id
         AND expired_event.kind = 'reservation_expired'
        WHERE reservation.organization_id = target_organization
        ON CONFLICT (reservation_id) DO NOTHING;
    END LOOP;
    PERFORM pg_catalog.set_config('claridez.organization_id', '', true);
END
$cutover$;
SET CONSTRAINTS ALL IMMEDIATE;
"""


TENANT_AND_GUARDIANS_SQL = r"""
ALTER TABLE public.commercial_reservation NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.commercial_eventrequest NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_venue NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_space NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.operations_eventpreparation NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.operations_preparationitem NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public.commercial_reservation
    ADD CONSTRAINT scheduling_reservation_tenant_root_fk
        FOREIGN KEY (organization_id, root_id)
        REFERENCES public.commercial_reservation (organization_id, id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT scheduling_reservation_tenant_predecessor_fk
        FOREIGN KEY (organization_id, predecessor_id)
        REFERENCES public.commercial_reservation (organization_id, id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT scheduling_reservation_tenant_confirmation_source_fk
        FOREIGN KEY (organization_id, confirmation_source_id)
        REFERENCES public.commercial_reservation (organization_id, id)
        DEFERRABLE INITIALLY DEFERRED;
CREATE UNIQUE INDEX scheduling_reservation_predecessor_uq
    ON public.commercial_reservation (organization_id, predecessor_id)
    WHERE predecessor_id IS NOT NULL;

ALTER TABLE public.scheduling_spaceschedulepolicy
    ADD CONSTRAINT scheduling_policy_tenant_space_fk
        FOREIGN KEY (organization_id, space_id)
        REFERENCES public.organizations_space (organization_id, id);
ALTER TABLE public.scheduling_scheduleblock
    ADD CONSTRAINT scheduling_block_tenant_venue_fk
        FOREIGN KEY (organization_id, venue_id)
        REFERENCES public.organizations_venue (organization_id, id),
    ADD CONSTRAINT scheduling_block_tenant_creator_fk
        FOREIGN KEY (organization_id, created_by_membership_id)
        REFERENCES public.organizations_membership (organization_id, id),
    ADD CONSTRAINT scheduling_block_tenant_ender_fk
        FOREIGN KEY (organization_id, ended_by_membership_id)
        REFERENCES public.organizations_membership (organization_id, id);
ALTER TABLE public.scheduling_scheduleblocktarget
    ADD CONSTRAINT scheduling_target_tenant_block_fk
        FOREIGN KEY (organization_id, block_id)
        REFERENCES public.scheduling_scheduleblock (organization_id, id),
    ADD CONSTRAINT scheduling_target_tenant_space_fk
        FOREIGN KEY (organization_id, space_id)
        REFERENCES public.organizations_space (organization_id, id);
ALTER TABLE public.scheduling_scheduleevent
    ADD CONSTRAINT scheduling_event_tenant_actor_fk
        FOREIGN KEY (organization_id, actor_membership_id)
        REFERENCES public.organizations_membership (organization_id, id),
    ADD CONSTRAINT scheduling_event_tenant_request_fk
        FOREIGN KEY (organization_id, event_request_id)
        REFERENCES public.commercial_eventrequest (organization_id, id),
    ADD CONSTRAINT scheduling_event_tenant_root_fk
        FOREIGN KEY (organization_id, root_reservation_id)
        REFERENCES public.commercial_reservation (organization_id, id),
    ADD CONSTRAINT scheduling_event_tenant_reservation_fk
        FOREIGN KEY (organization_id, reservation_id)
        REFERENCES public.commercial_reservation (organization_id, id),
    ADD CONSTRAINT scheduling_event_tenant_predecessor_fk
        FOREIGN KEY (organization_id, predecessor_id)
        REFERENCES public.commercial_reservation (organization_id, id),
    ADD CONSTRAINT scheduling_event_tenant_successor_fk
        FOREIGN KEY (organization_id, successor_id)
        REFERENCES public.commercial_reservation (organization_id, id),
    ADD CONSTRAINT scheduling_event_tenant_block_fk
        FOREIGN KEY (organization_id, block_id)
        REFERENCES public.scheduling_scheduleblock (organization_id, id);
ALTER TABLE public.scheduling_scheduleallocation
    ADD CONSTRAINT scheduling_allocation_tenant_space_fk
        FOREIGN KEY (organization_id, space_id)
        REFERENCES public.organizations_space (organization_id, id),
    ADD CONSTRAINT scheduling_allocation_tenant_reservation_fk
        FOREIGN KEY (organization_id, reservation_id)
        REFERENCES public.commercial_reservation (organization_id, id),
    ADD CONSTRAINT scheduling_allocation_tenant_target_fk
        FOREIGN KEY (organization_id, block_target_id)
        REFERENCES public.scheduling_scheduleblocktarget (organization_id, id),
    ADD CONSTRAINT scheduling_allocation_tenant_event_fk
        FOREIGN KEY (organization_id, source_event_id)
        REFERENCES public.scheduling_scheduleevent (organization_id, id),
    ADD CONSTRAINT scheduling_allocation_interval_canonical
        CHECK (
            NOT isempty(occupied_interval)
            AND lower(occupied_interval) < upper(occupied_interval)
            AND lower_inc(occupied_interval) AND NOT upper_inc(occupied_interval)
            AND NOT lower_inf(occupied_interval) AND NOT upper_inf(occupied_interval)
        );
ALTER TABLE public.scheduling_scheduleblock
    ADD CONSTRAINT scheduling_block_interval_canonical
        CHECK (
            NOT isempty(blocked_interval)
            AND lower(blocked_interval) < upper(blocked_interval)
            AND lower_inc(blocked_interval) AND NOT upper_inc(blocked_interval)
            AND NOT lower_inf(blocked_interval) AND NOT upper_inf(blocked_interval)
        );

ALTER TABLE public.operations_eventpreparation
    ADD CONSTRAINT operations_preparation_tenant_rescheduled_to_fk
        FOREIGN KEY (organization_id, rescheduled_to_reservation_id)
        REFERENCES public.commercial_reservation (organization_id, id);
ALTER TABLE public.operations_preparationitem
    ADD CONSTRAINT operations_item_tenant_carried_from_fk
        FOREIGN KEY (organization_id, carried_from_item_id)
        REFERENCES public.operations_preparationitem (organization_id, id);

ALTER TABLE public.commercial_reservation FORCE ROW LEVEL SECURITY;
ALTER TABLE public.commercial_eventrequest FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_venue FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations_space FORCE ROW LEVEL SECURITY;
ALTER TABLE public.operations_eventpreparation FORCE ROW LEVEL SECURITY;
ALTER TABLE public.operations_preparationitem FORCE ROW LEVEL SECURITY;

ALTER TABLE public.commercial_reservation
    DROP CONSTRAINT IF EXISTS commercial_reservation_lifecycle_evidence;
ALTER TABLE public.commercial_reservation
    ADD CONSTRAINT commercial_reservation_lifecycle_evidence
    CHECK (
        (status <> 'confirmed' OR confirmation_source_id IS NOT NULL)
        AND (status NOT IN ('provisional', 'expired') OR confirmation_source_id IS NULL)
        AND (
            (status = 'cancelled' AND cancelled_at IS NOT NULL
                AND cancelled_by_membership_id IS NOT NULL
                AND btrim(cancellation_reason) <> '')
            OR
            (status <> 'cancelled' AND cancelled_at IS NULL
                AND cancelled_by_membership_id IS NULL AND cancellation_reason = '')
        )
    );

DROP TRIGGER IF EXISTS commercial_reservation_transition ON public.commercial_reservation;
CREATE OR REPLACE FUNCTION public.claridez_guard_reservation_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status IN ('expired', 'cancelled', 'rescheduled')
           AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
               (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'terminal reservations are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
            (OLD.status = 'provisional' AND NEW.status IN
                ('confirmed', 'expired', 'cancelled', 'rescheduled'))
            OR (OLD.status = 'confirmed' AND NEW.status IN ('cancelled', 'rescheduled'))
        ) THEN
            RAISE EXCEPTION 'invalid reservation transition' USING ERRCODE = '23514';
        END IF;
        IF ROW(NEW.organization_id, NEW.event_request_id, NEW.quotation_version_id,
               NEW.root_id, NEW.predecessor_id, NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.organization_id, OLD.event_request_id, OLD.quotation_version_id,
               OLD.root_id, OLD.predecessor_id, OLD.created_at) THEN
            RAISE EXCEPTION 'reservation chain identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.confirmed_at IS NOT NULL AND ROW(
            NEW.confirmation_kind, NEW.recognized_deposit_amount,
            NEW.deposit_reported_at, NEW.deposit_reference, NEW.confirmed_at,
            NEW.confirmed_by_membership_id, NEW.waiver_reason,
            NEW.waiver_authorized_at, NEW.waiver_authorized_by_membership_id
        ) IS DISTINCT FROM ROW(
            OLD.confirmation_kind, OLD.recognized_deposit_amount,
            OLD.deposit_reported_at, OLD.deposit_reference, OLD.confirmed_at,
            OLD.confirmed_by_membership_id, OLD.waiver_reason,
            OLD.waiver_authorized_at, OLD.waiver_authorized_by_membership_id
        ) THEN
            RAISE EXCEPTION 'reservation confirmation evidence is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'reservation update requires next revision' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.revision <> 1 THEN
        RAISE EXCEPTION 'reservation must start at revision one' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_reservation_transition() FROM PUBLIC;
CREATE TRIGGER commercial_reservation_transition
BEFORE INSERT OR UPDATE ON public.commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_reservation_transition();

DROP TRIGGER IF EXISTS commercial_reservation_coherence ON public.commercial_reservation;
CREATE OR REPLACE FUNCTION public.claridez_validate_reservation_coherence()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    expected_request_id uuid;
    expected_space_id uuid;
    expected_interval tstzrange;
    expected_timezone text;
    quotation_status text;
    predecessor_row record;
    source_row record;
BEGIN
    SELECT quotation.event_request_id, version.space_snapshot_id,
           tstzrange(version.event_starts_at_snapshot, version.event_ends_at_snapshot, '[)'),
           version.event_timezone_snapshot, version.status
    INTO expected_request_id, expected_space_id, expected_interval,
         expected_timezone, quotation_status
    FROM public.commercial_quotationversion AS version
    JOIN public.commercial_quotation AS quotation
      ON quotation.organization_id = version.organization_id
     AND quotation.id = version.quotation_id
    WHERE version.organization_id = NEW.organization_id
      AND version.id = NEW.quotation_version_id;
    IF NOT FOUND OR quotation_status IS DISTINCT FROM 'accepted'
       OR NEW.event_request_id IS DISTINCT FROM expected_request_id THEN
        RAISE EXCEPTION 'reservation requires matching accepted commercial evidence'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.predecessor_id IS NULL THEN
        IF NEW.root_id <> NEW.id OR NEW.space_id <> expected_space_id
           OR NEW.event_interval IS DISTINCT FROM expected_interval
           OR NEW.event_timezone IS DISTINCT FROM expected_timezone THEN
            RAISE EXCEPTION 'reservation root does not match quotation snapshot'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT organization_id, event_request_id, quotation_version_id, root_id
        INTO predecessor_row
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND id = NEW.predecessor_id;
        IF NOT FOUND OR predecessor_row.event_request_id <> NEW.event_request_id
           OR predecessor_row.quotation_version_id <> NEW.quotation_version_id
           OR predecessor_row.root_id <> NEW.root_id OR NEW.root_id = NEW.id THEN
            RAISE EXCEPTION 'reservation successor breaks its chain'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.confirmation_source_id = NEW.id AND NEW.confirmed_at IS NOT NULL THEN
        NULL;
    ELSIF NEW.confirmation_source_id IS NOT NULL THEN
        SELECT root_id, event_request_id, quotation_version_id, confirmed_at
        INTO source_row
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND id = NEW.confirmation_source_id;
        IF NOT FOUND OR source_row.root_id <> NEW.root_id
           OR source_row.event_request_id <> NEW.event_request_id
           OR source_row.quotation_version_id <> NEW.quotation_version_id
           OR source_row.confirmed_at IS NULL THEN
            RAISE EXCEPTION 'reservation confirmation source is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_reservation_coherence() FROM PUBLIC;
CREATE TRIGGER commercial_reservation_coherence
BEFORE INSERT OR UPDATE ON public.commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_reservation_coherence();

CREATE FUNCTION public.claridez_reject_schedule_event_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    RAISE EXCEPTION 'schedule events are append-only' USING ERRCODE = '23514';
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_reject_schedule_event_change() FROM PUBLIC;
CREATE TRIGGER scheduling_event_immutable
BEFORE UPDATE OR DELETE ON public.scheduling_scheduleevent
FOR EACH ROW EXECUTE FUNCTION public.claridez_reject_schedule_event_change();

CREATE FUNCTION public.claridez_guard_schedule_projection_identity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' AND ROW(
        NEW.id, NEW.organization_id, NEW.space_id,
        NEW.reservation_id, NEW.block_target_id, NEW.occupied_interval, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.id, OLD.organization_id, OLD.space_id,
        OLD.reservation_id, OLD.block_target_id, OLD.occupied_interval, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'schedule allocation identity and snapshot are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_schedule_projection_identity() FROM PUBLIC;
CREATE TRIGGER scheduling_allocation_identity_guard
BEFORE UPDATE ON public.scheduling_scheduleallocation
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_schedule_projection_identity();

CREATE FUNCTION public.claridez_guard_schedule_target_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'schedule block targets are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_schedule_target_change() FROM PUBLIC;
CREATE TRIGGER scheduling_target_immutable
BEFORE UPDATE OR DELETE ON public.scheduling_scheduleblocktarget
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_schedule_target_change();

CREATE FUNCTION public.claridez_scheduling_expire_for_space(
    target_organization uuid,
    target_space uuid
)
RETURNS integer
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    reservation_row record;
    expiration_event_id uuid;
    expired_count integer := 0;
    previous_context text;
BEGIN
    IF target_organization IS DISTINCT FROM public.claridez_current_organization_id() THEN
        RAISE EXCEPTION 'tenant scope does not match expiration target' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(target_organization::text || ':' || target_space::text, 0)
    );
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    FOR reservation_row IN
        SELECT * FROM public.commercial_reservation
        WHERE organization_id = target_organization
          AND space_id = target_space
          AND status = 'provisional'
          AND hold_expires_at <= transaction_timestamp()
        ORDER BY root_id, id
        FOR UPDATE
    LOOP
        expiration_event_id := md5(reservation_row.id::text || ':p8:expired')::uuid;
        UPDATE public.commercial_reservation
        SET status = 'expired', revision = revision + 1, updated_at = transaction_timestamp()
        WHERE organization_id = target_organization AND id = reservation_row.id;
        INSERT INTO public.scheduling_scheduleevent (
            id, organization_id, kind, source, actor_membership_id, reason,
            event_request_id, root_reservation_id, reservation_id,
            predecessor_id, successor_id, block_id, aggregate_revision,
            previous_snapshot, new_snapshot, idempotency_key, payload_hash,
            occurred_at, recorded_at
        ) VALUES (
            expiration_event_id, target_organization,
            'reservation_expired', 'database_expiration', NULL, '',
            reservation_row.event_request_id, reservation_row.root_id, reservation_row.id,
            NULL, NULL, NULL, reservation_row.revision + 1,
            jsonb_build_object('status', 'provisional', 'revision', reservation_row.revision),
            jsonb_build_object('status', 'expired', 'revision', reservation_row.revision + 1),
            md5(reservation_row.id::text || ':p8:expired:key')::uuid,
            md5(reservation_row.id::text || ':p8:expired:payload') ||
                md5('claridez:' || reservation_row.id::text || ':p8:expired:payload'),
            transaction_timestamp(), transaction_timestamp()
        ) ON CONFLICT DO NOTHING;
        UPDATE public.scheduling_scheduleallocation
        SET is_blocking = false,
            source_revision = reservation_row.revision + 1,
            source_event_id = expiration_event_id,
            updated_at = transaction_timestamp()
        WHERE organization_id = target_organization
          AND reservation_id = reservation_row.id;
        UPDATE public.commercial_eventrequest AS request
        SET status = 'quoted', updated_at = transaction_timestamp()
        WHERE request.organization_id = target_organization
          AND request.id = reservation_row.event_request_id
          AND request.status = 'accepted'
          AND NOT EXISTS (
              SELECT 1 FROM public.commercial_reservation AS active
              WHERE active.organization_id = target_organization
                AND active.event_request_id = reservation_row.event_request_id
                AND active.status IN ('provisional', 'confirmed')
          );
        expired_count := expired_count + 1;
    END LOOP;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN expired_count;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_scheduling_expire_for_space(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claridez_scheduling_expire_for_space(uuid, uuid)
TO claridez_app, claridez_migrator, claridez_test_runner;

CREATE FUNCTION public.claridez_expire_before_schedule_allocation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF NEW.is_blocking AND pg_trigger_depth() = 1 THEN
        PERFORM public.claridez_scheduling_expire_for_space(
            NEW.organization_id, NEW.space_id
        );
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_expire_before_schedule_allocation() FROM PUBLIC;
CREATE TRIGGER scheduling_allocation_expire_due
BEFORE INSERT OR UPDATE OF is_blocking ON public.scheduling_scheduleallocation
FOR EACH ROW EXECUTE FUNCTION public.claridez_expire_before_schedule_allocation();

CREATE FUNCTION public.claridez_validate_scheduling_integrity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    target_organization uuid;
    previous_context text;
BEGIN
    target_organization := coalesce(NEW.organization_id, OLD.organization_id);
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', target_organization::text, true
    );
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM public.commercial_reservation AS reservation
            LEFT JOIN public.scheduling_scheduleallocation AS allocation
              ON allocation.organization_id = reservation.organization_id
             AND allocation.reservation_id = reservation.id
            WHERE reservation.organization_id = target_organization
              AND (
                  allocation.id IS NULL
                  OR allocation.space_id <> reservation.space_id
                  OR allocation.source_revision <> reservation.revision
                  OR allocation.occupied_interval IS DISTINCT FROM tstzrange(
                      lower(reservation.event_interval)
                        - make_interval(mins => reservation.setup_minutes
                            + reservation.buffer_before_minutes),
                      upper(reservation.event_interval)
                        + make_interval(mins => reservation.teardown_minutes
                            + reservation.buffer_after_minutes), '[)')
                  OR allocation.is_blocking IS DISTINCT FROM
                      (reservation.status IN ('provisional', 'confirmed'))
              )
        ) THEN
            RAISE EXCEPTION 'reservation allocation diverges from scheduling authority'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM public.commercial_reservation AS predecessor
            LEFT JOIN public.commercial_reservation AS successor
              ON successor.organization_id = predecessor.organization_id
             AND successor.predecessor_id = predecessor.id
            WHERE predecessor.organization_id = target_organization
              AND predecessor.status = 'rescheduled'
              AND (
                  successor.id IS NULL
                  OR successor.root_id <> predecessor.root_id
                  OR successor.event_request_id <> predecessor.event_request_id
                  OR successor.quotation_version_id <> predecessor.quotation_version_id
                  OR successor.status NOT IN ('provisional', 'confirmed')
                  OR NOT EXISTS (
                      SELECT 1 FROM public.scheduling_scheduleevent AS event
                      WHERE event.organization_id = predecessor.organization_id
                        AND event.kind = 'reservation_rescheduled'
                        AND event.predecessor_id = predecessor.id
                        AND event.successor_id = successor.id
                        AND event.root_reservation_id = predecessor.root_id
                  )
              )
        ) THEN
            RAISE EXCEPTION 'rescheduled reservation requires one coherent successor and event'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            WITH RECURSIVE ancestry AS (
                SELECT id AS origin, id, predecessor_id, ARRAY[id] AS path, false AS cycle
                FROM public.commercial_reservation
                WHERE organization_id = target_organization
                UNION ALL
                SELECT ancestry.origin, predecessor.id, predecessor.predecessor_id,
                       ancestry.path || predecessor.id,
                       predecessor.id = ANY(ancestry.path)
                FROM ancestry
                JOIN public.commercial_reservation AS predecessor
                  ON predecessor.organization_id = target_organization
                 AND predecessor.id = ancestry.predecessor_id
                WHERE NOT ancestry.cycle
            )
            SELECT 1 FROM ancestry WHERE cycle
        ) THEN
            RAISE EXCEPTION 'reservation chain contains a cycle' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM public.scheduling_scheduleblocktarget AS target
            JOIN public.scheduling_scheduleblock AS block
              ON block.organization_id = target.organization_id AND block.id = target.block_id
            LEFT JOIN public.scheduling_scheduleallocation AS allocation
              ON allocation.organization_id = target.organization_id
             AND allocation.block_target_id = target.id
            WHERE target.organization_id = target_organization
              AND (
                  allocation.id IS NULL OR allocation.space_id <> target.space_id
                  OR allocation.occupied_interval IS DISTINCT FROM block.blocked_interval
                  OR allocation.source_revision <> block.revision
                  OR allocation.is_blocking IS DISTINCT FROM (block.status = 'active')
              )
        ) THEN
            RAISE EXCEPTION 'block allocation diverges from scheduling authority'
                USING ERRCODE = '23514';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', coalesce(previous_context, ''), true
        );
        RAISE;
    END;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_scheduling_integrity() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER scheduling_reservation_integrity_guard
AFTER INSERT OR UPDATE ON public.commercial_reservation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_scheduling_integrity();
CREATE CONSTRAINT TRIGGER scheduling_allocation_integrity_guard
AFTER INSERT OR UPDATE OR DELETE ON public.scheduling_scheduleallocation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_scheduling_integrity();
CREATE CONSTRAINT TRIGGER scheduling_event_integrity_guard
AFTER INSERT ON public.scheduling_scheduleevent
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_scheduling_integrity();
CREATE CONSTRAINT TRIGGER scheduling_block_integrity_guard
AFTER INSERT OR UPDATE ON public.scheduling_scheduleblock
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_scheduling_integrity();
CREATE CONSTRAINT TRIGGER scheduling_target_integrity_guard
AFTER INSERT OR DELETE ON public.scheduling_scheduleblocktarget
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.claridez_validate_scheduling_integrity();

CREATE FUNCTION public.claridez_guard_carried_preparation_item()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    source_item record;
    source_preparation record;
BEGIN
    IF NEW.carried_from_item_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.baseline_key IS NOT NULL OR NEW.status <> 'pending'
       OR NEW.due_on IS NOT NULL OR NEW.resolved_at IS NOT NULL
       OR NEW.resolved_by_membership_id IS NOT NULL OR NEW.status_note <> ''
       OR NEW.revision <> 1 THEN
        RAISE EXCEPTION 'carried free item must restart as pending'
            USING ERRCODE = '23514';
    END IF;
    SELECT item.*, preparation.status AS preparation_status,
           preparation.rescheduled_to_reservation_id
    INTO source_item
    FROM public.operations_preparationitem AS item
    JOIN public.operations_eventpreparation AS preparation
      ON preparation.organization_id = item.organization_id
     AND preparation.reservation_id = item.preparation_id
    WHERE item.organization_id = NEW.organization_id
      AND item.id = NEW.carried_from_item_id;
    SELECT reservation_id INTO source_preparation
    FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id;
    IF NOT FOUND OR source_item.baseline_key IS NOT NULL
       OR source_item.preparation_status <> 'rescheduled'
       OR source_item.rescheduled_to_reservation_id <> NEW.preparation_id
       OR ROW(NEW.title, NEW.section, NEW.is_required, NEW.notes)
          IS DISTINCT FROM ROW(
              source_item.title, source_item.section,
              source_item.is_required, source_item.notes
          ) THEN
        RAISE EXCEPTION 'carried item provenance is invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_carried_preparation_item() FROM PUBLIC;
CREATE TRIGGER operations_carried_item_guard
BEFORE INSERT OR UPDATE ON public.operations_preparationitem
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_carried_preparation_item();
"""


OPERATIONS_GUARDS_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_guard_event_preparation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    reservation_status text;
    reservation_successor uuid;
    baseline_count integer;
    expected_baseline_count integer;
    item_count integer;
    distinct_position_count integer;
    minimum_position integer;
    maximum_position integer;
    unresolved_count integer;
    blocked_count integer;
    final_status text;
    responsible_count integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('preparing', 'cancelled') THEN
            RAISE EXCEPTION 'invalid initial preparation status' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF OLD.status IN ('completed', 'cancelled', 'rescheduled')
           AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
               (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'terminal preparations are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
            (OLD.status = 'preparing' AND NEW.status IN ('ready', 'cancelled', 'rescheduled'))
            OR (OLD.status = 'ready' AND NEW.status IN
                ('preparing', 'in_progress', 'cancelled', 'rescheduled'))
            OR (OLD.status = 'in_progress' AND NEW.status = 'completed')
        ) THEN
            RAISE EXCEPTION 'invalid preparation transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT status INTO reservation_status
    FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id;
    IF NEW.status IN ('preparing', 'ready', 'in_progress', 'completed')
       AND reservation_status IS DISTINCT FROM 'confirmed' THEN
        RAISE EXCEPTION 'active preparation requires confirmed reservation'
            USING ERRCODE = '23514';
    ELSIF NEW.status = 'cancelled' AND reservation_status IS DISTINCT FROM 'cancelled' THEN
        RAISE EXCEPTION 'cancelled preparation requires cancelled reservation'
            USING ERRCODE = '23514';
    ELSIF NEW.status = 'rescheduled' THEN
        SELECT id INTO reservation_successor
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id
          AND predecessor_id = NEW.reservation_id;
        IF reservation_status IS DISTINCT FROM 'rescheduled'
           OR reservation_successor IS DISTINCT FROM NEW.rescheduled_to_reservation_id THEN
            RAISE EXCEPTION 'rescheduled preparation requires reservation successor'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status = 'preparing' AND (NEW.ready_at IS NOT NULL
       OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'preparing evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'ready' AND (NEW.ready_at IS NULL
       OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'ready evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'in_progress' AND (NEW.ready_at IS NULL
       OR NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'execution evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'completed' AND (NEW.ready_at IS NULL
       OR NEW.started_at IS NULL OR NEW.completed_at IS NULL) THEN
        RAISE EXCEPTION 'completion evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status IN ('cancelled', 'rescheduled') AND
       (NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'terminal evidence is inconsistent' USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ready' AND (TG_OP = 'INSERT' OR OLD.status <> 'ready') THEN
        IF NEW.responsible_membership_id IS NULL THEN
            RAISE EXCEPTION 'ready preparation requires responsible' USING ERRCODE = '23514';
        END IF;
        SELECT count(*) INTO responsible_count
        FROM public.organizations_membership
        WHERE organization_id = NEW.organization_id
          AND id = NEW.responsible_membership_id
          AND status = 'active' AND role IN ('owner', 'administrator', 'operations');
        SELECT
            count(*) FILTER (WHERE baseline_key IS NOT NULL),
            count(*) FILTER (WHERE baseline_key IN (
                'space_layout', 'guest_count', 'special_requirements', 'entry_schedule',
                'furniture', 'decoration', 'final_readiness_review')),
            count(*), count(DISTINCT position), min(position), max(position),
            count(*) FILTER (WHERE is_required AND status NOT IN ('completed', 'not_applicable')),
            count(*) FILTER (WHERE status = 'blocked'),
            max(status) FILTER (WHERE baseline_key = 'final_readiness_review')
        INTO baseline_count, expected_baseline_count, item_count, distinct_position_count,
            minimum_position, maximum_position, unresolved_count, blocked_count, final_status
        FROM public.operations_preparationitem
        WHERE organization_id = NEW.organization_id AND preparation_id = NEW.reservation_id;
        IF responsible_count <> 1 OR baseline_count <> 7 OR expected_baseline_count <> 7
           OR item_count <> distinct_position_count OR minimum_position <> 1
           OR maximum_position <> item_count OR unresolved_count <> 0 OR blocked_count <> 0
           OR final_status IS DISTINCT FROM 'completed' THEN
            RAISE EXCEPTION 'preparation is not ready' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_event_preparation() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_guard_preparation_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE current_status text; current_revision integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'preparation transitions are append-only' USING ERRCODE = '23514';
    END IF;
    SELECT status, revision INTO current_status, current_revision
    FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id;
    IF current_status IS DISTINCT FROM NEW.to_status
       OR current_revision IS DISTINCT FROM NEW.preparation_revision THEN
        RAISE EXCEPTION 'transition does not match preparation' USING ERRCODE = '23514';
    END IF;
    IF NOT (
        (NEW.cause = 'initialized' AND NEW.from_status IS NULL
            AND NEW.to_status = 'preparing' AND NEW.preparation_revision = 1)
        OR (NEW.cause = 'readiness_declared' AND NEW.from_status = 'preparing'
            AND NEW.to_status = 'ready')
        OR (NEW.cause = 'checklist_reopened' AND NEW.from_status = 'ready'
            AND NEW.to_status = 'preparing')
        OR (NEW.cause = 'execution_started' AND NEW.from_status = 'ready'
            AND NEW.to_status = 'in_progress')
        OR (NEW.cause = 'execution_completed' AND NEW.from_status = 'in_progress'
            AND NEW.to_status = 'completed')
        OR (NEW.cause = 'commercial_cancellation'
            AND NEW.from_status IN ('preparing', 'ready') AND NEW.to_status = 'cancelled')
        OR (NEW.cause = 'schedule_reschedule'
            AND NEW.from_status IN ('preparing', 'ready') AND NEW.to_status = 'rescheduled')
    ) THEN
        RAISE EXCEPTION 'invalid preparation transition cause' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_preparation_transition() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_guard_commercial_operations()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    previous_context text;
    preparation_status text;
    successor_id uuid;
    successor_status text;
    successor_preparation_status text;
    baseline_count integer;
    initialized_count integer;
    terminal_transition_count integer;
BEGIN
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', NEW.organization_id::text, true);
    SELECT status INTO preparation_status
    FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.id;
    SELECT count(*) FILTER (WHERE baseline_key IS NOT NULL)
    INTO baseline_count
    FROM public.operations_preparationitem
    WHERE organization_id = NEW.organization_id AND preparation_id = NEW.id;
    SELECT count(*) FILTER (WHERE cause = 'initialized'),
           count(*) FILTER (WHERE cause IN ('commercial_cancellation', 'schedule_reschedule'))
    INTO initialized_count, terminal_transition_count
    FROM public.operations_preparationtransition
    WHERE organization_id = NEW.organization_id AND preparation_id = NEW.id;
    IF NEW.status = 'confirmed' THEN
        IF preparation_status NOT IN ('preparing', 'ready', 'in_progress', 'completed')
           OR baseline_count <> 7 OR initialized_count <> 1 THEN
            RAISE EXCEPTION 'confirmed reservation requires complete operation aggregate'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'cancelled' AND NEW.confirmation_source_id IS NOT NULL THEN
        IF preparation_status <> 'cancelled' OR baseline_count <> 7
           OR initialized_count <> 1 OR terminal_transition_count <> 1 THEN
            RAISE EXCEPTION 'confirmed cancellation requires cancelled operation aggregate'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'rescheduled' THEN
        SELECT id, status INTO successor_id, successor_status
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND predecessor_id = NEW.id;
        SELECT status INTO successor_preparation_status
        FROM public.operations_eventpreparation
        WHERE organization_id = NEW.organization_id AND reservation_id = successor_id;
        IF NEW.confirmation_source_id IS NOT NULL THEN
            IF preparation_status <> 'rescheduled'
               OR successor_status <> 'confirmed'
               OR successor_preparation_status <> 'preparing'
               OR terminal_transition_count <> 1 THEN
                RAISE EXCEPTION 'confirmed reschedule requires replacement operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF preparation_status IS NOT NULL OR successor_preparation_status IS NOT NULL THEN
            RAISE EXCEPTION 'provisional reschedule cannot create operation aggregate'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.confirmation_source_id IS NULL AND preparation_status IS NOT NULL THEN
        RAISE EXCEPTION 'unconfirmed reservation cannot have operation aggregate'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_commercial_operations() FROM PUBLIC;
"""


OPERATIONS_GUARDS_REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_guard_event_preparation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    reservation_status text;
    baseline_count integer;
    expected_baseline_count integer;
    item_count integer;
    distinct_position_count integer;
    minimum_position integer;
    maximum_position integer;
    unresolved_count integer;
    blocked_count integer;
    final_status text;
    responsible_count integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('preparing', 'cancelled') THEN
            RAISE EXCEPTION 'invalid initial preparation status' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF OLD.status IN ('completed', 'cancelled')
           AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
               (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'terminal preparations are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
            (OLD.status = 'preparing' AND NEW.status IN ('ready', 'cancelled'))
            OR (OLD.status = 'ready' AND NEW.status IN
                ('preparing', 'in_progress', 'cancelled'))
            OR (OLD.status = 'in_progress' AND NEW.status = 'completed')
        ) THEN
            RAISE EXCEPTION 'invalid preparation transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT status INTO reservation_status
    FROM public.commercial_reservation
    WHERE organization_id = NEW.organization_id AND id = NEW.reservation_id;
    IF NEW.status IN ('preparing', 'ready', 'in_progress', 'completed')
       AND reservation_status IS DISTINCT FROM 'confirmed' THEN
        RAISE EXCEPTION 'active preparation requires confirmed reservation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'cancelled' AND reservation_status IS DISTINCT FROM 'cancelled' THEN
        RAISE EXCEPTION 'cancelled preparation requires cancelled reservation'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND ((OLD.status = 'in_progress' AND NEW.status = 'cancelled')
       OR (OLD.status = 'completed' AND NEW.status = 'cancelled')) THEN
        RAISE EXCEPTION 'executed preparation cannot be cancelled' USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'preparing' AND (NEW.ready_at IS NOT NULL
       OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'preparing evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'ready' AND (NEW.ready_at IS NULL
       OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'ready evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'in_progress' AND (NEW.ready_at IS NULL
       OR NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'execution evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'completed' AND (NEW.ready_at IS NULL
       OR NEW.started_at IS NULL OR NEW.completed_at IS NULL) THEN
        RAISE EXCEPTION 'completion evidence is inconsistent' USING ERRCODE = '23514';
    ELSIF NEW.status = 'cancelled' AND (NEW.started_at IS NOT NULL
       OR NEW.completed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'cancellation evidence is inconsistent' USING ERRCODE = '23514';
    END IF;
    IF (NEW.ready_at IS NOT NULL AND NEW.started_at IS NOT NULL
       AND NEW.ready_at > NEW.started_at)
       OR (NEW.started_at IS NOT NULL AND NEW.completed_at IS NOT NULL
       AND NEW.started_at > NEW.completed_at) THEN
        RAISE EXCEPTION 'preparation evidence chronology is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ready' AND (TG_OP = 'INSERT' OR OLD.status <> 'ready') THEN
        IF NEW.responsible_membership_id IS NULL THEN
            RAISE EXCEPTION 'ready preparation requires responsible' USING ERRCODE = '23514';
        END IF;
        SELECT count(*) INTO responsible_count
        FROM public.organizations_membership
        WHERE organization_id = NEW.organization_id
          AND id = NEW.responsible_membership_id
          AND status = 'active' AND role IN ('owner', 'administrator', 'operations');
        IF responsible_count <> 1 THEN
            RAISE EXCEPTION 'ready preparation requires eligible responsible'
                USING ERRCODE = '23514';
        END IF;
        SELECT
            count(*) FILTER (WHERE baseline_key IS NOT NULL),
            count(*) FILTER (WHERE baseline_key IN (
                'space_layout', 'guest_count', 'special_requirements', 'entry_schedule',
                'furniture', 'decoration', 'final_readiness_review')),
            count(*), count(DISTINCT position), min(position), max(position),
            count(*) FILTER (WHERE is_required AND status NOT IN ('completed', 'not_applicable')),
            count(*) FILTER (WHERE status = 'blocked'),
            max(status) FILTER (WHERE baseline_key = 'final_readiness_review')
        INTO baseline_count, expected_baseline_count, item_count, distinct_position_count,
            minimum_position, maximum_position, unresolved_count, blocked_count, final_status
        FROM public.operations_preparationitem
        WHERE organization_id = NEW.organization_id AND preparation_id = NEW.reservation_id;
        IF baseline_count <> 7 OR expected_baseline_count <> 7
           OR item_count <> distinct_position_count OR minimum_position <> 1
           OR maximum_position <> item_count OR unresolved_count <> 0 OR blocked_count <> 0
           OR final_status IS DISTINCT FROM 'completed' THEN
            RAISE EXCEPTION 'preparation is not ready' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_event_preparation() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_guard_preparation_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE current_status text; current_revision integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'preparation transitions are append-only' USING ERRCODE = '23514';
    END IF;
    SELECT status, revision INTO current_status, current_revision
    FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id;
    IF current_status IS DISTINCT FROM NEW.to_status
       OR current_revision IS DISTINCT FROM NEW.preparation_revision THEN
        RAISE EXCEPTION 'transition does not match preparation' USING ERRCODE = '23514';
    END IF;
    IF NOT (
        (NEW.cause = 'initialized' AND NEW.from_status IS NULL
            AND NEW.to_status = 'preparing' AND NEW.preparation_revision = 1)
        OR (NEW.cause = 'readiness_declared' AND NEW.from_status = 'preparing'
            AND NEW.to_status = 'ready')
        OR (NEW.cause = 'checklist_reopened' AND NEW.from_status = 'ready'
            AND NEW.to_status = 'preparing')
        OR (NEW.cause = 'execution_started' AND NEW.from_status = 'ready'
            AND NEW.to_status = 'in_progress')
        OR (NEW.cause = 'execution_completed' AND NEW.from_status = 'in_progress'
            AND NEW.to_status = 'completed')
        OR (NEW.cause = 'commercial_cancellation'
            AND NEW.from_status IN ('preparing', 'ready') AND NEW.to_status = 'cancelled')
    ) THEN
        RAISE EXCEPTION 'invalid preparation transition cause' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_preparation_transition() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claridez_guard_commercial_operations()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    previous_context text;
    preparation_status text;
    baseline_count integer;
    expected_baseline_count integer;
    initialized_count integer;
    cancellation_count integer;
    current_reservation_status text;
    current_confirmed_at timestamptz;
BEGIN
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', NEW.organization_id::text, true);
    BEGIN
        SELECT status, confirmed_at
        INTO current_reservation_status, current_confirmed_at
        FROM public.commercial_reservation
        WHERE organization_id = NEW.organization_id AND id = NEW.id;
        SELECT status INTO preparation_status
        FROM public.operations_eventpreparation
        WHERE organization_id = NEW.organization_id AND reservation_id = NEW.id;
        SELECT
            count(*) FILTER (WHERE baseline_key IS NOT NULL),
            count(*) FILTER (WHERE baseline_key IN (
                'space_layout', 'guest_count', 'special_requirements', 'entry_schedule',
                'furniture', 'decoration', 'final_readiness_review'))
        INTO baseline_count, expected_baseline_count
        FROM public.operations_preparationitem
        WHERE organization_id = NEW.organization_id AND preparation_id = NEW.id;
        SELECT count(*) INTO initialized_count
        FROM public.operations_preparationtransition
        WHERE organization_id = NEW.organization_id
          AND preparation_id = NEW.id AND cause = 'initialized';
        SELECT count(*) INTO cancellation_count
        FROM public.operations_preparationtransition
        WHERE organization_id = NEW.organization_id
          AND preparation_id = NEW.id AND cause = 'commercial_cancellation';
        IF current_reservation_status = 'confirmed' THEN
            IF preparation_status IS NULL OR preparation_status = 'cancelled'
               OR baseline_count <> 7 OR expected_baseline_count <> 7
               OR initialized_count <> 1 THEN
                RAISE EXCEPTION 'confirmed reservation requires complete operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_reservation_status = 'cancelled' AND current_confirmed_at IS NOT NULL THEN
            IF preparation_status IS DISTINCT FROM 'cancelled'
               OR baseline_count <> 7 OR expected_baseline_count <> 7
               OR initialized_count <> 1 OR cancellation_count <> 1 THEN
                RAISE EXCEPTION 'commercial cancellation requires cancelled operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF current_confirmed_at IS NULL
              OR current_reservation_status IN ('provisional', 'expired') THEN
            IF preparation_status IS NOT NULL THEN
                RAISE EXCEPTION 'unconfirmed reservation cannot have operation aggregate'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', coalesce(previous_context, ''), true
        );
        RAISE;
    END;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_commercial_operations() FROM PUBLIC;
"""


ROLLBACK_PREFLIGHT_SQL = r"""
DO $rollback_preflight$
BEGIN
    IF EXISTS (SELECT 1 FROM public.scheduling_scheduleblock) THEN
        RAISE EXCEPTION 'P8 rollback requires recovery: schedule blocks already exist'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.commercial_reservation
        WHERE predecessor_id IS NOT NULL OR root_id <> id OR status = 'rescheduled'
           OR setup_minutes <> 0 OR teardown_minutes <> 0
           OR buffer_before_minutes <> 0 OR buffer_after_minutes <> 0
    ) THEN
        RAISE EXCEPTION 'P8 rollback requires recovery: reservation contains P8-only state'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.operations_eventpreparation
        WHERE status = 'rescheduled' OR rescheduled_to_reservation_id IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM public.operations_preparationitem
        WHERE carried_from_item_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'P8 rollback requires recovery: operations contains P8-only state'
            USING ERRCODE = '23514';
    END IF;
END
$rollback_preflight$;
"""


RLS_AND_PRIVILEGES_SQL = r"""
REVOKE ALL ON TABLE
    public.scheduling_spaceschedulepolicy,
    public.scheduling_scheduleblock,
    public.scheduling_scheduleblocktarget,
    public.scheduling_scheduleevent,
    public.scheduling_scheduleallocation
FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON TABLE
    public.scheduling_spaceschedulepolicy,
    public.scheduling_scheduleblock,
    public.scheduling_scheduleallocation
TO claridez_app;
GRANT SELECT, INSERT ON TABLE
    public.scheduling_scheduleblocktarget,
    public.scheduling_scheduleevent
TO claridez_app;

ALTER TABLE public.scheduling_spaceschedulepolicy ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_spaceschedulepolicy FORCE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleblock ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleblock FORCE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleblocktarget ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleblocktarget FORCE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleevent ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleevent FORCE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleallocation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduling_scheduleallocation FORCE ROW LEVEL SECURITY;

CREATE POLICY scheduling_policy_tenant_policy
ON public.scheduling_spaceschedulepolicy AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY scheduling_block_tenant_policy
ON public.scheduling_scheduleblock AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY scheduling_target_tenant_policy
ON public.scheduling_scheduleblocktarget AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY scheduling_event_tenant_policy
ON public.scheduling_scheduleevent AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
CREATE POLICY scheduling_allocation_tenant_policy
ON public.scheduling_scheduleallocation AS PERMISSIVE FOR ALL
TO claridez_app, claridez_migrator, claridez_test_runner
USING (organization_id = public.claridez_current_organization_id())
WITH CHECK (organization_id = public.claridez_current_organization_id());
"""


REVERSE_SQL = r"""
ALTER TABLE public.scheduling_scheduleallocation
    DROP CONSTRAINT IF EXISTS scheduling_allocation_tenant_event_fk,
    DROP CONSTRAINT IF EXISTS scheduling_allocation_tenant_target_fk,
    DROP CONSTRAINT IF EXISTS scheduling_allocation_tenant_reservation_fk,
    DROP CONSTRAINT IF EXISTS scheduling_allocation_tenant_space_fk,
    DROP CONSTRAINT IF EXISTS scheduling_allocation_interval_canonical;
ALTER TABLE public.scheduling_scheduleevent
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_block_fk,
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_successor_fk,
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_predecessor_fk,
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_reservation_fk,
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_root_fk,
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_request_fk,
    DROP CONSTRAINT IF EXISTS scheduling_event_tenant_actor_fk;
ALTER TABLE public.scheduling_scheduleblocktarget
    DROP CONSTRAINT IF EXISTS scheduling_target_tenant_space_fk,
    DROP CONSTRAINT IF EXISTS scheduling_target_tenant_block_fk;
ALTER TABLE public.scheduling_scheduleblock
    DROP CONSTRAINT IF EXISTS scheduling_block_tenant_ender_fk,
    DROP CONSTRAINT IF EXISTS scheduling_block_tenant_creator_fk,
    DROP CONSTRAINT IF EXISTS scheduling_block_tenant_venue_fk,
    DROP CONSTRAINT IF EXISTS scheduling_block_interval_canonical;
ALTER TABLE public.scheduling_spaceschedulepolicy
    DROP CONSTRAINT IF EXISTS scheduling_policy_tenant_space_fk;
ALTER TABLE public.operations_preparationitem
    DROP CONSTRAINT IF EXISTS operations_item_tenant_carried_from_fk;
ALTER TABLE public.operations_eventpreparation
    DROP CONSTRAINT IF EXISTS operations_preparation_tenant_rescheduled_to_fk;
ALTER TABLE public.commercial_reservation
    DROP CONSTRAINT IF EXISTS scheduling_reservation_tenant_confirmation_source_fk,
    DROP CONSTRAINT IF EXISTS scheduling_reservation_tenant_predecessor_fk,
    DROP CONSTRAINT IF EXISTS scheduling_reservation_tenant_root_fk;
DROP INDEX IF EXISTS public.scheduling_reservation_predecessor_uq;

DROP TRIGGER IF EXISTS operations_carried_item_guard ON public.operations_preparationitem;
DROP FUNCTION IF EXISTS public.claridez_guard_carried_preparation_item();
DROP TRIGGER IF EXISTS scheduling_target_integrity_guard ON public.scheduling_scheduleblocktarget;
DROP TRIGGER IF EXISTS scheduling_block_integrity_guard ON public.scheduling_scheduleblock;
DROP TRIGGER IF EXISTS scheduling_event_integrity_guard ON public.scheduling_scheduleevent;
DROP TRIGGER IF EXISTS scheduling_allocation_integrity_guard
    ON public.scheduling_scheduleallocation;
DROP TRIGGER IF EXISTS scheduling_reservation_integrity_guard ON public.commercial_reservation;
DROP FUNCTION IF EXISTS public.claridez_validate_scheduling_integrity();
DROP TRIGGER IF EXISTS scheduling_allocation_expire_due ON public.scheduling_scheduleallocation;
DROP FUNCTION IF EXISTS public.claridez_expire_before_schedule_allocation();
DROP FUNCTION IF EXISTS public.claridez_scheduling_expire_for_space(uuid, uuid);
DROP TRIGGER IF EXISTS scheduling_target_immutable ON public.scheduling_scheduleblocktarget;
DROP FUNCTION IF EXISTS public.claridez_guard_schedule_target_change();
DROP TRIGGER IF EXISTS scheduling_allocation_identity_guard ON public.scheduling_scheduleallocation;
DROP FUNCTION IF EXISTS public.claridez_guard_schedule_projection_identity();
DROP TRIGGER IF EXISTS scheduling_event_immutable ON public.scheduling_scheduleevent;
DROP FUNCTION IF EXISTS public.claridez_reject_schedule_event_change();

ALTER TABLE public.commercial_reservation
    DROP CONSTRAINT IF EXISTS commercial_reservation_lifecycle_evidence,
    ADD CONSTRAINT commercial_reservation_lifecycle_evidence
    CHECK (
        (status <> 'confirmed' OR confirmed_at IS NOT NULL)
        AND (status NOT IN ('provisional', 'expired') OR confirmed_at IS NULL)
        AND (
            (status = 'cancelled' AND cancelled_at IS NOT NULL
                AND cancelled_by_membership_id IS NOT NULL
                AND btrim(cancellation_reason) <> '')
            OR
            (status <> 'cancelled' AND cancelled_at IS NULL
                AND cancelled_by_membership_id IS NULL AND cancellation_reason = '')
        )
    );

DROP TRIGGER IF EXISTS commercial_reservation_transition ON public.commercial_reservation;
CREATE OR REPLACE FUNCTION public.claridez_guard_reservation_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF OLD.status IN ('expired', 'cancelled')
       AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'terminal reservations are immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'provisional' AND NEW.status IN ('confirmed', 'expired', 'cancelled'))
        OR (OLD.status = 'confirmed' AND NEW.status = 'cancelled')
    ) THEN
        RAISE EXCEPTION 'invalid reservation transition' USING ERRCODE = '23514';
    END IF;
    IF OLD.confirmed_at IS NOT NULL AND ROW(
        NEW.confirmation_kind, NEW.recognized_deposit_amount,
        NEW.deposit_reported_at, NEW.deposit_reference, NEW.confirmed_at,
        NEW.confirmed_by_membership_id, NEW.waiver_reason,
        NEW.waiver_authorized_at, NEW.waiver_authorized_by_membership_id
    ) IS DISTINCT FROM ROW(
        OLD.confirmation_kind, OLD.recognized_deposit_amount,
        OLD.deposit_reported_at, OLD.deposit_reference, OLD.confirmed_at,
        OLD.confirmed_by_membership_id, OLD.waiver_reason,
        OLD.waiver_authorized_at, OLD.waiver_authorized_by_membership_id
    ) THEN
        RAISE EXCEPTION 'reservation confirmation evidence is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_reservation_transition() FROM PUBLIC;
CREATE TRIGGER commercial_reservation_transition
BEFORE UPDATE ON public.commercial_reservation
FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_reservation_transition();

CREATE OR REPLACE FUNCTION public.claridez_validate_reservation_coherence()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    expected_request_id uuid;
    expected_space_id uuid;
    expected_interval tstzrange;
    expected_timezone text;
    quotation_status text;
BEGIN
    SELECT quotation.event_request_id, version.space_snapshot_id,
           tstzrange(version.event_starts_at_snapshot, version.event_ends_at_snapshot, '[)'),
           version.event_timezone_snapshot, version.status
    INTO expected_request_id, expected_space_id, expected_interval,
         expected_timezone, quotation_status
    FROM public.commercial_quotationversion AS version
    JOIN public.commercial_quotation AS quotation
      ON quotation.organization_id = version.organization_id
     AND quotation.id = version.quotation_id
    WHERE version.organization_id = NEW.organization_id
      AND version.id = NEW.quotation_version_id;
    IF NOT FOUND OR quotation_status IS DISTINCT FROM 'accepted' THEN
        RAISE EXCEPTION 'reservation requires an accepted quotation version'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.event_request_id IS DISTINCT FROM expected_request_id
       OR NEW.space_id IS DISTINCT FROM expected_space_id
       OR NEW.event_interval IS DISTINCT FROM expected_interval
       OR NEW.event_timezone IS DISTINCT FROM expected_timezone THEN
        RAISE EXCEPTION 'reservation does not match quotation snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_validate_reservation_coherence() FROM PUBLIC;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0008_delete_reservation"),
        ("operations", "0004_remove_eventpreparation_operations_preparation_status_valid_and_more"),
        ("scheduling", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(CUTOVER_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(TENANT_AND_GUARDIANS_SQL, REVERSE_SQL),
        migrations.RunSQL(OPERATIONS_GUARDS_SQL, OPERATIONS_GUARDS_REVERSE_SQL),
        migrations.RunSQL(RLS_AND_PRIVILEGES_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(migrations.RunSQL.noop, ROLLBACK_PREFLIGHT_SQL),
    ]
