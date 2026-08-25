# ruff: noqa: E501

from django.db import migrations

PRIVATE_TABLES = (
    "operations_operationaltemplate",
    "operations_operationaltemplateversion",
    "operations_templatereadinessdefinition",
    "operations_templatephasedefinition",
    "operations_templateroledefinition",
    "operations_templateresourceneed",
    "operations_operationalplansnapshot",
    "operations_operationalverification",
    "operations_operationalverificationevent",
    "operations_operationalphasefact",
    "operations_operationalresponsibility",
    "operations_operationalincident",
    "operations_operationalincidentevent",
    "operations_operationalchangeproposal",
    "operations_operationalchangedecision",
    "operations_readinessdeviation",
    "operations_operationalresourcewindow",
    "operations_operationalevidence",
    "operations_posteventclose",
    "operations_posteventclosecorrection",
    "operations_operationcommand",
)

APPEND_ONLY_TABLES = (
    "operations_templatereadinessdefinition",
    "operations_templatephasedefinition",
    "operations_templateroledefinition",
    "operations_templateresourceneed",
    "operations_operationalplansnapshot",
    "operations_operationalverificationevent",
    "operations_operationalphasefact",
    "operations_operationalresponsibility",
    "operations_operationalincidentevent",
    "operations_operationalchangedecision",
    "operations_readinessdeviation",
    "operations_operationalresourcewindow",
    "operations_operationalevidence",
    "operations_posteventclose",
    "operations_posteventclosecorrection",
    "operations_operationcommand",
)

TENANT_FOREIGN_KEYS = (
    ("operations_operationaltemplate", "event_type_id", "catalog_eventtype", "op13_tpl_type_fk"),
    (
        "operations_operationaltemplate",
        "created_by_membership_id",
        "organizations_membership",
        "op13_tpl_actor_fk",
    ),
    (
        "operations_operationaltemplateversion",
        "template_id",
        "operations_operationaltemplate",
        "op13_tplver_tpl_fk",
    ),
    (
        "operations_operationaltemplateversion",
        "created_by_membership_id",
        "organizations_membership",
        "op13_tplver_actor_fk",
    ),
    (
        "operations_operationaltemplateversion",
        "published_by_membership_id",
        "organizations_membership",
        "op13_tplver_pub_fk",
    ),
    (
        "operations_templatereadinessdefinition",
        "version_id",
        "operations_operationaltemplateversion",
        "op13_readydef_ver_fk",
    ),
    (
        "operations_templatephasedefinition",
        "version_id",
        "operations_operationaltemplateversion",
        "op13_phasedef_ver_fk",
    ),
    (
        "operations_templateroledefinition",
        "version_id",
        "operations_operationaltemplateversion",
        "op13_roledef_ver_fk",
    ),
    (
        "operations_templateresourceneed",
        "version_id",
        "operations_operationaltemplateversion",
        "op13_need_ver_fk",
    ),
    (
        "operations_templateresourceneed",
        "resource_id",
        "resources_resource",
        "op13_need_resource_fk",
    ),
    (
        "operations_operationalplansnapshot",
        "preparation_id",
        "operations_eventpreparation",
        "op13_snapshot_prep_fk",
    ),
    (
        "operations_operationalplansnapshot",
        "template_version_id",
        "operations_operationaltemplateversion",
        "op13_snapshot_ver_fk",
    ),
    (
        "operations_preparationitem",
        "template_readiness_definition_id",
        "operations_templatereadinessdefinition",
        "op13_item_readydef_fk",
    ),
    (
        "operations_operationalverification",
        "preparation_id",
        "operations_eventpreparation",
        "op13_verify_prep_fk",
    ),
    (
        "operations_operationalverification",
        "snapshot_id",
        "operations_operationalplansnapshot",
        "op13_verify_snapshot_fk",
    ),
    (
        "operations_operationalverification",
        "definition_id",
        "operations_templatephasedefinition",
        "op13_verify_def_fk",
    ),
    (
        "operations_operationalverification",
        "completed_by_membership_id",
        "organizations_membership",
        "op13_verify_actor_fk",
    ),
    (
        "operations_operationalverificationevent",
        "verification_id",
        "operations_operationalverification",
        "op13_vevent_verify_fk",
    ),
    (
        "operations_operationalverificationevent",
        "actor_membership_id",
        "organizations_membership",
        "op13_vevent_actor_fk",
    ),
    (
        "operations_operationalphasefact",
        "preparation_id",
        "operations_eventpreparation",
        "op13_phase_prep_fk",
    ),
    (
        "operations_operationalphasefact",
        "actor_membership_id",
        "organizations_membership",
        "op13_phase_actor_fk",
    ),
    (
        "operations_operationalphasefact",
        "corrects_id",
        "operations_operationalphasefact",
        "op13_phase_corrects_fk",
    ),
    (
        "operations_operationalresponsibility",
        "preparation_id",
        "operations_eventpreparation",
        "op13_resp_prep_fk",
    ),
    (
        "operations_operationalresponsibility",
        "snapshot_id",
        "operations_operationalplansnapshot",
        "op13_resp_snapshot_fk",
    ),
    (
        "operations_operationalresponsibility",
        "membership_id",
        "organizations_membership",
        "op13_resp_member_fk",
    ),
    (
        "operations_operationalresponsibility",
        "assigned_by_membership_id",
        "organizations_membership",
        "op13_resp_actor_fk",
    ),
    (
        "operations_operationalresponsibility",
        "supersedes_id",
        "operations_operationalresponsibility",
        "op13_resp_previous_fk",
    ),
    (
        "operations_operationalincident",
        "preparation_id",
        "operations_eventpreparation",
        "op13_incident_prep_fk",
    ),
    (
        "operations_operationalincident",
        "responsible_membership_id",
        "organizations_membership",
        "op13_incident_resp_fk",
    ),
    (
        "operations_operationalincident",
        "reported_by_membership_id",
        "organizations_membership",
        "op13_incident_actor_fk",
    ),
    (
        "operations_operationalincidentevent",
        "incident_id",
        "operations_operationalincident",
        "op13_ievent_incident_fk",
    ),
    (
        "operations_operationalincidentevent",
        "actor_membership_id",
        "organizations_membership",
        "op13_ievent_actor_fk",
    ),
    (
        "operations_operationalincidentevent",
        "responsible_membership_id",
        "organizations_membership",
        "op13_ievent_resp_fk",
    ),
    (
        "operations_operationalincidentevent",
        "corrects_id",
        "operations_operationalincidentevent",
        "op13_ievent_corrects_fk",
    ),
    (
        "operations_operationalchangeproposal",
        "preparation_id",
        "operations_eventpreparation",
        "op13_change_prep_fk",
    ),
    (
        "operations_operationalchangeproposal",
        "proposed_by_membership_id",
        "organizations_membership",
        "op13_change_actor_fk",
    ),
    (
        "operations_operationalchangedecision",
        "proposal_id",
        "operations_operationalchangeproposal",
        "op13_decision_proposal_fk",
    ),
    (
        "operations_operationalchangedecision",
        "decided_by_membership_id",
        "organizations_membership",
        "op13_decision_actor_fk",
    ),
    (
        "operations_readinessdeviation",
        "item_id",
        "operations_preparationitem",
        "op13_deviation_item_fk",
    ),
    (
        "operations_readinessdeviation",
        "decision_id",
        "operations_operationalchangedecision",
        "op13_deviation_decision_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "preparation_id",
        "operations_eventpreparation",
        "op13_window_prep_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "snapshot_id",
        "operations_operationalplansnapshot",
        "op13_window_snapshot_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "resource_need_id",
        "operations_templateresourceneed",
        "op13_window_need_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "resource_id",
        "resources_resource",
        "op13_window_resource_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "reservation_id",
        "commercial_reservation",
        "op13_window_reservation_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "schedule_allocation_id",
        "scheduling_scheduleallocation",
        "op13_window_allocation_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "schedule_event_id",
        "scheduling_scheduleevent",
        "op13_window_event_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "predecessor_id",
        "operations_operationalresourcewindow",
        "op13_window_previous_fk",
    ),
    (
        "operations_operationalresourcewindow",
        "authorization_decision_id",
        "operations_operationalchangedecision",
        "op13_window_decision_fk",
    ),
    (
        "operations_operationalevidence",
        "preparation_id",
        "operations_eventpreparation",
        "op13_evidence_prep_fk",
    ),
    (
        "operations_operationalevidence",
        "document_file_id",
        "documents_privatedomainfile",
        "op13_evidence_file_fk",
    ),
    (
        "operations_operationalevidence",
        "linked_by_membership_id",
        "organizations_membership",
        "op13_evidence_actor_fk",
    ),
    (
        "operations_posteventclose",
        "preparation_id",
        "operations_eventpreparation",
        "op13_close_prep_fk",
    ),
    (
        "operations_posteventclose",
        "closed_by_membership_id",
        "organizations_membership",
        "op13_close_actor_fk",
    ),
    (
        "operations_posteventclosecorrection",
        "close_id",
        "operations_posteventclose",
        "op13_closecorr_close_fk",
    ),
    (
        "operations_posteventclosecorrection",
        "corrected_by_membership_id",
        "organizations_membership",
        "op13_closecorr_actor_fk",
    ),
)


def tenant_fk_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} ADD CONSTRAINT {name} FOREIGN KEY "
        f"(organization_id, {column}) REFERENCES public.{target} "
        f"(organization_id, {'reservation_id' if target == 'operations_eventpreparation' else 'id'}) "
        "DEFERRABLE INITIALLY DEFERRED;"
        for table, column, target, name in TENANT_FOREIGN_KEYS
    )


def tenant_fk_reverse_sql() -> str:
    return "\n".join(
        f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name};"
        for table, _, _, name in reversed(TENANT_FOREIGN_KEYS)
    )


def rls_sql() -> str:
    statements = []
    for table in PRIVATE_TABLES:
        privileges = "SELECT, INSERT" if table in APPEND_ONLY_TABLES else "SELECT, INSERT, UPDATE"
        statements.extend(
            [
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, claridez_app;",
                f"GRANT {privileges} ON TABLE public.{table} TO claridez_app;",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO claridez_test_runner;",
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
                f"CREATE POLICY {table}_tenant_policy ON public.{table} AS PERMISSIVE FOR ALL "
                "USING (organization_id = public.claridez_current_organization_id()) "
                "WITH CHECK (organization_id = public.claridez_current_organization_id());",
            ]
        )
    statements.append(
        "REVOKE DELETE, TRUNCATE ON TABLE "
        + ", ".join(f"public.{table}" for table in PRIVATE_TABLES)
        + " FROM claridez_app;"
    )
    return "\n".join(statements)


def rls_reverse_sql() -> str:
    return "\n".join(
        f"DROP POLICY IF EXISTS {table}_tenant_policy ON public.{table}; "
        f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY; "
        f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;"
        for table in PRIVATE_TABLES
    )


def append_only_trigger_sql() -> str:
    return "\n".join(
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_p13_immutable();"
        for table in APPEND_ONLY_TABLES
    )


def append_only_trigger_reverse_sql() -> str:
    return "\n".join(
        f"DROP TRIGGER IF EXISTS {table}_immutable ON public.{table};"
        for table in APPEND_ONLY_TABLES
    )


GUARDIAN_SQL = r"""
CREATE FUNCTION public.claridez_operations_p13_immutable()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    RAISE EXCEPTION 'advanced operation fact is append-only' USING ERRCODE = '23514';
END;
$function$;

CREATE FUNCTION public.claridez_operations_guard_template_version()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'operational template versions cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.organization_id, NEW.template_id, NEW.version, NEW.created_by_membership_id,
           NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.template_id, OLD.version, OLD.created_by_membership_id,
           OLD.created_at) THEN
        RAISE EXCEPTION 'operational template version identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'draft' AND NEW.status = 'published' THEN
        IF NEW.published_at IS NULL OR NEW.published_by_membership_id IS NULL
           OR NEW.retired_at IS NOT NULL OR NEW.content_sha256 = '' THEN
            RAISE EXCEPTION 'published template version lacks evidence' USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'published' AND NEW.status = 'retired' THEN
        IF NEW.retired_at IS NULL OR ROW(NEW.content_sha256, NEW.published_at,
           NEW.published_by_membership_id) IS DISTINCT FROM
           ROW(OLD.content_sha256, OLD.published_at, OLD.published_by_membership_id) THEN
            RAISE EXCEPTION 'retired template version rewrites publication' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'invalid operational template version transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_template_version() FROM PUBLIC;
CREATE TRIGGER operations_template_version_guard
BEFORE UPDATE OR DELETE ON public.operations_operationaltemplateversion
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_template_version();

CREATE FUNCTION public.claridez_operations_guard_item_source()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    IF NEW.source_kind = 'baseline_5_2' THEN
        IF NEW.baseline_key IS NULL OR NEW.template_readiness_definition_id IS NOT NULL
           OR NEW.carried_from_item_id IS NOT NULL OR NEW.template_role_key <> '' THEN
            RAISE EXCEPTION 'baseline readiness provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.source_kind = 'manual' THEN
        IF NEW.baseline_key IS NOT NULL OR NEW.template_readiness_definition_id IS NOT NULL
           OR NEW.template_role_key <> '' THEN
            RAISE EXCEPTION 'manual readiness provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.source_kind = 'p13_template_readiness' THEN
        IF NEW.baseline_key IS NOT NULL OR NEW.template_readiness_definition_id IS NULL
           OR NEW.carried_from_item_id IS NOT NULL THEN
            RAISE EXCEPTION 'template readiness provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown readiness provenance' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND ROW(NEW.organization_id, NEW.preparation_id, NEW.client_request_id,
       NEW.baseline_key, NEW.source_kind, NEW.template_readiness_definition_id,
       NEW.carried_from_item_id, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.organization_id, OLD.preparation_id, OLD.client_request_id,
       OLD.baseline_key, OLD.source_kind, OLD.template_readiness_definition_id,
       OLD.carried_from_item_id, OLD.created_at) THEN
        RAISE EXCEPTION 'readiness provenance is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_item_source() FROM PUBLIC;
CREATE TRIGGER operations_item_source_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.operations_preparationitem
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_item_source();

CREATE FUNCTION public.claridez_operations_validate_readiness()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE target_organization uuid; target_preparation uuid; previous_context text;
BEGIN
    target_organization := coalesce(NEW.organization_id, OLD.organization_id);
    IF TG_TABLE_NAME = 'operations_readinessdeviation' THEN
        SELECT preparation_id INTO target_preparation
        FROM public.operations_preparationitem
        WHERE organization_id = target_organization AND id = NEW.item_id;
    ELSE
        target_preparation := coalesce(NEW.preparation_id, OLD.preparation_id);
    END IF;
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', target_organization::text, true);
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM public.operations_preparationitem item
            JOIN public.operations_templatereadinessdefinition definition
              ON definition.organization_id = item.organization_id
             AND definition.id = item.template_readiness_definition_id
            JOIN public.operations_operationalplansnapshot snapshot
              ON snapshot.organization_id = item.organization_id
             AND snapshot.preparation_id = item.preparation_id
            LEFT JOIN LATERAL (
                SELECT value
                FROM pg_catalog.jsonb_array_elements(
                    snapshot.canonical_payload -> 'materialized_readiness'
                ) value
                WHERE value ->> 'definition_id' = definition.id::text
                LIMIT 1
            ) materialized ON true
            LEFT JOIN LATERAL (
                SELECT deviation.effective_payload, proposal.proposed_payload,
                       decision.approved
                FROM public.operations_readinessdeviation deviation
                JOIN public.operations_operationalchangedecision decision
                  ON decision.organization_id = deviation.organization_id
                 AND decision.id = deviation.decision_id
                JOIN public.operations_operationalchangeproposal proposal
                  ON proposal.organization_id = decision.organization_id
                 AND proposal.id = decision.proposal_id
                WHERE deviation.organization_id = item.organization_id
                  AND deviation.item_id = item.id
                  AND proposal.preparation_id = item.preparation_id
                  AND proposal.scope = 'readiness' AND proposal.target_id = item.id
                ORDER BY deviation.created_at DESC, deviation.id DESC LIMIT 1
            ) latest ON true
            WHERE item.organization_id = target_organization
              AND item.preparation_id = target_preparation
              AND item.source_kind = 'p13_template_readiness'
              AND (
                  definition.version_id <> snapshot.template_version_id
                  OR materialized.value IS NULL
                  OR (latest.effective_payload IS NULL AND ROW(
                      item.title, item.section, item.is_required, item.due_on,
                      item.template_role_key
                  ) IS DISTINCT FROM ROW(
                      materialized.value ->> 'title', materialized.value ->> 'section',
                      (materialized.value ->> 'is_required')::boolean,
                      (materialized.value ->> 'due_on')::date,
                      materialized.value ->> 'role_key'
                  ))
                  OR (latest.effective_payload IS NOT NULL AND (
                      latest.approved IS DISTINCT FROM true OR ROW(
                          item.title, item.section, item.is_required, item.due_on,
                          item.template_role_key, item.position
                      ) IS DISTINCT FROM ROW(
                          latest.effective_payload ->> 'title',
                          latest.effective_payload ->> 'section',
                          (latest.effective_payload ->> 'is_required')::boolean,
                          (latest.effective_payload ->> 'due_on')::date,
                          latest.effective_payload ->> 'template_role_key',
                          (latest.effective_payload ->> 'position')::integer
                      )
                  ))
              )
        ) THEN
            RAISE EXCEPTION 'template readiness projection diverges from snapshot and ledger'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM public.operations_preparationitem first_item
            JOIN public.operations_templatereadinessdefinition first_definition
              ON first_definition.organization_id = first_item.organization_id
             AND first_definition.id = first_item.template_readiness_definition_id
            JOIN public.operations_preparationitem second_item
              ON second_item.organization_id = first_item.organization_id
             AND second_item.preparation_id = first_item.preparation_id
             AND second_item.source_kind = 'p13_template_readiness'
            JOIN public.operations_templatereadinessdefinition second_definition
              ON second_definition.organization_id = second_item.organization_id
             AND second_definition.id = second_item.template_readiness_definition_id
            WHERE first_item.organization_id = target_organization
              AND first_item.preparation_id = target_preparation
              AND first_item.source_kind = 'p13_template_readiness'
              AND first_definition.position < second_definition.position
              AND first_item.position >= second_item.position
              AND NOT EXISTS (
                  SELECT 1 FROM public.operations_readinessdeviation deviation
                  JOIN public.operations_operationalchangedecision decision
                    ON decision.organization_id = deviation.organization_id
                   AND decision.id = deviation.decision_id AND decision.approved
                  JOIN public.operations_operationalchangeproposal proposal
                    ON proposal.organization_id = decision.organization_id
                   AND proposal.id = decision.proposal_id
                  WHERE deviation.organization_id = first_item.organization_id
                    AND deviation.item_id IN (first_item.id, second_item.id)
                    AND proposal.proposed_payload ? 'position'
              )
        ) THEN
            RAISE EXCEPTION 'template readiness relative order diverges without authorization'
                USING ERRCODE = '23514';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_catalog.set_config('claridez.organization_id', coalesce(previous_context, ''), true);
        RAISE;
    END;
    PERFORM pg_catalog.set_config('claridez.organization_id', coalesce(previous_context, ''), true);
    RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_validate_readiness() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER operations_item_readiness_complete
AFTER INSERT OR UPDATE OR DELETE ON public.operations_preparationitem
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_readiness();
CREATE CONSTRAINT TRIGGER operations_deviation_readiness_complete
AFTER INSERT ON public.operations_readinessdeviation
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_readiness();

CREATE FUNCTION public.claridez_operations_guard_phase_fact()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE preparation_status text; current_preparation_revision integer; corrected record;
BEGIN
    SELECT status, revision INTO preparation_status, current_preparation_revision
    FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id;
    IF preparation_status IS NULL OR NEW.preparation_revision <> current_preparation_revision THEN
        RAISE EXCEPTION 'phase fact revision diverges from EventPreparation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.corrects_id IS NOT NULL THEN
        SELECT * INTO corrected FROM public.operations_operationalphasefact
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id;
        IF corrected.id IS NULL OR corrected.preparation_id <> NEW.preparation_id
           OR corrected.phase <> NEW.phase OR corrected.fact_kind <> NEW.fact_kind
           OR NEW.provenance <> 'authorized_correction' OR NEW.correction_reason = '' THEN
            RAISE EXCEPTION 'phase correction provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.provenance <> 'user_observation' OR NEW.correction_reason <> '' THEN
        RAISE EXCEPTION 'phase observation provenance is invalid' USING ERRCODE = '23514';
    ELSIF NEW.phase = 'setup' AND preparation_status NOT IN ('preparing', 'ready') THEN
        RAISE EXCEPTION 'setup observation is not allowed in this preparation state'
            USING ERRCODE = '23514';
    ELSIF NEW.phase = 'teardown' AND preparation_status <> 'completed' THEN
        RAISE EXCEPTION 'teardown observation requires completed execution'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_phase_fact() FROM PUBLIC;
CREATE TRIGGER operations_phase_fact_guard
BEFORE INSERT ON public.operations_operationalphasefact
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_phase_fact();

CREATE FUNCTION public.claridez_operations_validate_phase_timeline()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE started_at timestamptz; completed_at timestamptz; previous_context text;
BEGIN
    previous_context := pg_catalog.current_setting('claridez.organization_id', true);
    PERFORM pg_catalog.set_config('claridez.organization_id', NEW.organization_id::text, true);
    WITH RECURSIVE chain AS (
        SELECT fact.id, fact.corrects_id, fact.observed_at, 0 depth
        FROM public.operations_operationalphasefact fact
        WHERE fact.organization_id = NEW.organization_id
          AND fact.preparation_id = NEW.preparation_id
          AND fact.phase = NEW.phase AND fact.fact_kind = 'started'
          AND fact.corrects_id IS NULL
        UNION ALL
        SELECT correction.id, correction.corrects_id, correction.observed_at, chain.depth + 1
        FROM chain JOIN public.operations_operationalphasefact correction
          ON correction.organization_id = NEW.organization_id
         AND correction.corrects_id = chain.id
    ) SELECT observed_at INTO started_at FROM chain ORDER BY depth DESC LIMIT 1;
    WITH RECURSIVE chain AS (
        SELECT fact.id, fact.corrects_id, fact.observed_at, 0 depth
        FROM public.operations_operationalphasefact fact
        WHERE fact.organization_id = NEW.organization_id
          AND fact.preparation_id = NEW.preparation_id
          AND fact.phase = NEW.phase AND fact.fact_kind = 'completed'
          AND fact.corrects_id IS NULL
        UNION ALL
        SELECT correction.id, correction.corrects_id, correction.observed_at, chain.depth + 1
        FROM chain JOIN public.operations_operationalphasefact correction
          ON correction.organization_id = NEW.organization_id
         AND correction.corrects_id = chain.id
    ) SELECT observed_at INTO completed_at FROM chain ORDER BY depth DESC LIMIT 1;
    IF completed_at IS NOT NULL AND (started_at IS NULL OR completed_at < started_at) THEN
        RAISE EXCEPTION 'operational phase timeline is impossible' USING ERRCODE = '23514';
    END IF;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_validate_phase_timeline() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER operations_phase_timeline_complete
AFTER INSERT ON public.operations_operationalphasefact
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.claridez_operations_validate_phase_timeline();

CREATE FUNCTION public.claridez_operations_guard_window()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE preparation record; snapshot record; reservation record; allocation record;
        event record; need record; decision record; proposal record; predecessor_window record;
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
    IF preparation.reservation_id IS NULL OR snapshot.id IS NULL OR reservation.id IS NULL
       OR allocation.id IS NULL OR event.id IS NULL OR preparation.status NOT IN ('preparing', 'ready')
       OR preparation.reservation_id <> reservation.id OR NEW.preparation_id <> reservation.id
       OR NEW.root_reservation_id <> reservation.root_id OR snapshot.preparation_id <> preparation.reservation_id
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
             AND (event.new_snapshot ->> 'revision')::integer = reservation.revision)
       )
       OR NOT (NEW.required_interval <@ allocation.occupied_interval)
    THEN
        RAISE EXCEPTION 'operational window diverges from scheduling authority'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_kind = 'organization_template' THEN
        SELECT * INTO need FROM public.operations_templateresourceneed
        WHERE organization_id = NEW.organization_id AND id = NEW.resource_need_id;
        IF need.id IS NULL OR snapshot.source_kind <> 'organization'
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
REVOKE ALL ON FUNCTION public.claridez_operations_guard_window() FROM PUBLIC;
CREATE TRIGGER operations_resource_window_guard
BEFORE INSERT ON public.operations_operationalresourcewindow
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_window();

CREATE FUNCTION public.claridez_operations_guard_post_close()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE preparation_status text;
BEGIN
    SELECT status INTO preparation_status FROM public.operations_eventpreparation
    WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id;
    IF preparation_status <> 'completed'
       OR EXISTS (SELECT 1 FROM public.operations_operationalverification
           WHERE organization_id = NEW.organization_id AND preparation_id = NEW.preparation_id
             AND phase IN ('teardown', 'post_event') AND is_required AND status = 'pending')
       OR EXISTS (SELECT 1 FROM public.operations_operationalchangeproposal
           WHERE organization_id = NEW.organization_id AND preparation_id = NEW.preparation_id
             AND status = 'pending')
       OR EXISTS (SELECT 1 FROM public.operations_operationalincident
           WHERE organization_id = NEW.organization_id AND preparation_id = NEW.preparation_id
             AND (status = 'open' OR (status = 'contained' AND severity IN ('high', 'critical'))))
       OR EXISTS (SELECT 1 FROM public.resources_resourcerequirement
           WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id
             AND status = 'open')
       OR EXISTS (SELECT 1 FROM public.resources_resourceassignment
           WHERE organization_id = NEW.organization_id AND reservation_id = NEW.preparation_id
             AND status IN ('reserved', 'custody'))
       OR EXISTS (SELECT 1 FROM public.resources_resourcerequirement requirement
           WHERE requirement.organization_id = NEW.organization_id
             AND requirement.reservation_id = NEW.preparation_id AND requirement.status = 'shortage'
             AND NOT EXISTS (SELECT 1 FROM public.operations_operationalincident incident
                 JOIN public.operations_operationalevidence evidence
                   ON evidence.organization_id = incident.organization_id
                  AND evidence.preparation_id = incident.preparation_id
                  AND evidence.target_kind = 'incident'
                  AND evidence.target_id = incident.id
                 WHERE incident.organization_id = NEW.organization_id
                   AND incident.preparation_id = NEW.preparation_id
                   AND incident.incident_type = 'resource'))
       OR (EXISTS (SELECT 1 FROM public.resources_resourceassignment assignment
             WHERE assignment.organization_id = NEW.organization_id
               AND assignment.reservation_id = NEW.preparation_id
               AND assignment.status IN ('released', 'cancelled'))
           AND NOT EXISTS (SELECT 1 FROM public.operations_operationalincident incident
             WHERE incident.organization_id = NEW.organization_id
               AND incident.preparation_id = NEW.preparation_id
               AND incident.incident_type = 'resource')
           AND NOT EXISTS (SELECT 1 FROM public.operations_operationalchangedecision decision
             JOIN public.operations_operationalchangeproposal proposal
               ON proposal.organization_id = decision.organization_id
              AND proposal.id = decision.proposal_id
             WHERE decision.organization_id = NEW.organization_id AND decision.approved
               AND proposal.preparation_id = NEW.preparation_id
               AND proposal.scope IN ('resource_need', 'resource_window')))
    THEN
        RAISE EXCEPTION 'post-event close conditions are not satisfied' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION public.claridez_operations_guard_post_close() FROM PUBLIC;
CREATE TRIGGER operations_post_close_guard
BEFORE INSERT ON public.operations_posteventclose
FOR EACH ROW EXECUTE FUNCTION public.claridez_operations_guard_post_close();
"""

GUARDIAN_REVERSE = r"""
DROP TRIGGER IF EXISTS operations_post_close_guard ON public.operations_posteventclose;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_post_close();
DROP TRIGGER IF EXISTS operations_resource_window_guard ON public.operations_operationalresourcewindow;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_window();
DROP TRIGGER IF EXISTS operations_phase_timeline_complete ON public.operations_operationalphasefact;
DROP FUNCTION IF EXISTS public.claridez_operations_validate_phase_timeline();
DROP TRIGGER IF EXISTS operations_phase_fact_guard ON public.operations_operationalphasefact;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_phase_fact();
DROP TRIGGER IF EXISTS operations_deviation_readiness_complete ON public.operations_readinessdeviation;
DROP TRIGGER IF EXISTS operations_item_readiness_complete ON public.operations_preparationitem;
DROP FUNCTION IF EXISTS public.claridez_operations_validate_readiness();
DROP TRIGGER IF EXISTS operations_item_source_guard ON public.operations_preparationitem;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_item_source();
DROP TRIGGER IF EXISTS operations_template_version_guard ON public.operations_operationaltemplateversion;
DROP FUNCTION IF EXISTS public.claridez_operations_guard_template_version();
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0005_templateresourceneed_templateroledefinition_and_more")]

    operations = [
        migrations.RunSQL(tenant_fk_sql(), tenant_fk_reverse_sql()),
        migrations.RunSQL(rls_sql(), rls_reverse_sql()),
        migrations.RunSQL(
            "CREATE FUNCTION public.claridez_operations_p13_immutable() "
            "RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$ "
            "BEGIN RAISE EXCEPTION 'advanced operation fact is append-only' "
            "USING ERRCODE = '23514'; END; $$;\n" + append_only_trigger_sql(),
            append_only_trigger_reverse_sql()
            + "\nDROP FUNCTION IF EXISTS public.claridez_operations_p13_immutable();",
        ),
        migrations.RunSQL(
            GUARDIAN_SQL.replace(
                "CREATE FUNCTION public.claridez_operations_p13_immutable()\n"
                "RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$\n"
                "BEGIN\n"
                "    RAISE EXCEPTION 'advanced operation fact is append-only' USING ERRCODE = '23514';\n"
                "END;\n"
                "$function$;\n\n",
                "",
            ),
            GUARDIAN_REVERSE,
        ),
    ]
