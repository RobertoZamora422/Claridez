from __future__ import annotations

from pathlib import Path

from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Trim


def _previous_function_sql(file_name: str, function_name: str) -> str:
    source = (Path(__file__).parent / file_name).read_text(encoding="utf-8")
    marker = f"CREATE FUNCTION public.{function_name}()"
    start = source.index(marker)
    end = source.index("\n$function$;", start) + len("\n$function$;")
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


PRECHECK_SQL = r"""
DO $block$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.operations_posteventclose close
        JOIN public.operations_operationalincident incident
          ON incident.organization_id = close.organization_id
         AND incident.preparation_id = close.preparation_id
        WHERE incident.status = 'contained'
          AND incident.severity IN ('low', 'medium')
    ) THEN
        RAISE EXCEPTION
            'closed contained incidents predate explicit follow-up; refuse to invent history'
            USING ERRCODE = '23514';
    END IF;
END;
$block$;
"""


INCIDENT_EVENT_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_operations_guard_incident_event()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
DECLARE prior record; corrected record;
BEGIN
    IF NEW.impact = '' OR NEW.impact <> btrim(NEW.impact)
       OR NEW.follow_up <> btrim(NEW.follow_up) THEN
        RAISE EXCEPTION 'incident event text projection is invalid' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO prior FROM public.operations_operationalincidentevent
    WHERE organization_id = NEW.organization_id AND incident_id = NEW.incident_id
    ORDER BY incident_revision DESC, id DESC LIMIT 1;
    IF NEW.kind = 'opened' THEN
        IF prior.id IS NOT NULL OR NEW.incident_revision <> 1 OR NEW.from_status <> ''
           OR NEW.to_status <> 'open' OR NEW.corrects_id IS NOT NULL
           OR NEW.follow_up <> '' THEN
            RAISE EXCEPTION 'incident opening provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF prior.id IS NULL OR NEW.incident_revision <> prior.incident_revision + 1 THEN
        RAISE EXCEPTION 'incident event revision is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'contained' AND NOT (
        prior.to_status = 'open' AND NEW.from_status = 'open'
        AND NEW.to_status = 'contained' AND NEW.corrects_id IS NULL
        AND NEW.severity = prior.severity AND NEW.impact = prior.impact
        AND NEW.responsible_membership_id IS NOT DISTINCT FROM prior.responsible_membership_id
    ) THEN
        RAISE EXCEPTION 'incident containment transition is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'resolved' AND NOT (
        prior.to_status IN ('open', 'contained') AND NEW.from_status = prior.to_status
        AND NEW.to_status = 'resolved' AND NEW.corrects_id IS NULL
        AND NEW.severity = prior.severity AND NEW.impact = prior.impact
        AND NEW.follow_up = prior.follow_up
        AND NEW.responsible_membership_id IS NOT DISTINCT FROM prior.responsible_membership_id
    ) THEN
        RAISE EXCEPTION 'incident resolution transition is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'reassigned' AND NOT (
        NEW.from_status = prior.to_status AND NEW.to_status = prior.to_status
        AND NEW.corrects_id IS NULL AND NEW.severity = prior.severity
        AND NEW.impact = prior.impact AND NEW.follow_up = prior.follow_up
    ) THEN
        RAISE EXCEPTION 'incident reassignment provenance is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'impact_updated' AND NOT (
        NEW.from_status = prior.to_status AND NEW.to_status = prior.to_status
        AND NEW.corrects_id IS NULL AND NEW.severity = prior.severity
        AND NEW.follow_up = prior.follow_up
        AND NEW.responsible_membership_id IS NOT DISTINCT FROM prior.responsible_membership_id
    ) THEN
        RAISE EXCEPTION 'incident impact provenance is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'follow_up_updated' AND NOT (
        NEW.from_status = prior.to_status AND NEW.to_status = prior.to_status
        AND NEW.corrects_id IS NULL AND NEW.severity = prior.severity
        AND NEW.impact = prior.impact
        AND NEW.responsible_membership_id IS NOT DISTINCT FROM prior.responsible_membership_id
    ) THEN
        RAISE EXCEPTION 'incident follow-up provenance is invalid' USING ERRCODE = '23514';
    ELSIF NEW.kind = 'corrected' THEN
        SELECT * INTO corrected FROM public.operations_operationalincidentevent
        WHERE organization_id = NEW.organization_id AND id = NEW.corrects_id;
        IF corrected.id IS NULL OR corrected.incident_id <> NEW.incident_id
           OR NEW.from_status <> prior.to_status OR NEW.to_status <> prior.to_status THEN
            RAISE EXCEPTION 'incident correction provenance is invalid' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.kind NOT IN (
        'contained', 'resolved', 'reassigned', 'impact_updated', 'follow_up_updated', 'corrected'
    ) THEN
        RAISE EXCEPTION 'incident event kind is invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
"""


INCIDENT_PROJECTION_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_operations_validate_incident_projection()
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
       OR projection.impact <> latest.impact OR projection.follow_up <> latest.follow_up
       OR projection.responsible_membership_id IS DISTINCT FROM latest.responsible_membership_id
       OR projection.revision <> latest.incident_revision THEN
        RAISE EXCEPTION 'incident projection diverges from append-only ledger'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.operations_posteventclose close
        WHERE close.organization_id = target_organization
          AND close.preparation_id = projection.preparation_id
    ) AND projection.status = 'contained' AND (
        projection.severity NOT IN ('low', 'medium')
        OR projection.responsible_membership_id IS NULL
        OR projection.impact = '' OR projection.impact <> btrim(projection.impact)
        OR projection.follow_up = '' OR projection.follow_up <> btrim(projection.follow_up)
    ) THEN
        RAISE EXCEPTION 'incident correction invalidates post-event close'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_catalog.set_config(
        'claridez.organization_id', coalesce(previous_context, ''), true
    );
    RETURN NULL;
END;
$function$;
"""


_OLD_POST_CLOSE = _previous_function_sql(
    "0006_p13_integrity.py", "claridez_operations_guard_post_close"
)
POST_CLOSE_GUARD_SQL = _OLD_POST_CLOSE.replace(
    "AND (status = 'open' OR (status = 'contained' AND severity IN ('high', 'critical'))))",
    "AND (status = 'open' OR (status = 'contained' AND ("
    "severity IN ('high', 'critical') OR responsible_membership_id IS NULL "
    "OR impact = '' OR impact <> btrim(impact) "
    "OR follow_up = '' OR follow_up <> btrim(follow_up)))))",
)
if POST_CLOSE_GUARD_SQL == _OLD_POST_CLOSE:
    raise RuntimeError("The post-event close guardian source no longer matches operations.0006.")

FORWARD_GUARDIANS = "\n".join(
    (INCIDENT_EVENT_GUARD_SQL, INCIDENT_PROJECTION_GUARD_SQL, POST_CLOSE_GUARD_SQL)
)
REVERSE_GUARDIANS = "\n".join(
    (
        _previous_function_sql(
            "0011_p13_projection_guardians.py", "claridez_operations_guard_incident_event"
        ),
        _previous_function_sql(
            "0011_p13_projection_guardians.py",
            "claridez_operations_validate_incident_projection",
        ),
        _OLD_POST_CLOSE,
    )
)


class Migration(migrations.Migration):
    dependencies = [("operations", "0017_refresh_change_projection_guardian")]

    operations = [
        migrations.AddField(
            model_name="operationalincident",
            name="follow_up",
            field=models.CharField(blank=True, default="", max_length=1000),
        ),
        migrations.AlterField(
            model_name="operationalincidentevent",
            name="kind",
            field=models.CharField(
                choices=[
                    ("opened", "Abierta"),
                    ("contained", "Contenida"),
                    ("resolved", "Resuelta"),
                    ("reassigned", "Reasignada"),
                    ("impact_updated", "Impacto actualizado"),
                    ("follow_up_updated", "Seguimiento actualizado"),
                    ("corrected", "Corregida"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="operationalincidentevent",
            name="follow_up",
            field=models.CharField(blank=True, default="", max_length=1000),
        ),
        migrations.RunSQL(PRECHECK_SQL, migrations.RunSQL.noop),
        migrations.AddConstraint(
            model_name="operationalincident",
            constraint=models.CheckConstraint(
                condition=Q(impact=Trim("impact")) & ~Q(impact=""),
                name="operations_incident_impact_nonempty_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="operationalincident",
            constraint=models.CheckConstraint(
                condition=Q(follow_up="") | Q(follow_up=Trim("follow_up")),
                name="operations_incident_follow_up_normalized_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="operationalincidentevent",
            constraint=models.CheckConstraint(
                condition=Q(impact=Trim("impact")) & ~Q(impact=""),
                name="operations_incident_event_impact_nonempty_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="operationalincidentevent",
            constraint=models.CheckConstraint(
                condition=Q(follow_up="") | Q(follow_up=Trim("follow_up")),
                name="operations_incident_event_follow_up_normalized_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_GUARDIANS, REVERSE_GUARDIANS),
    ]
