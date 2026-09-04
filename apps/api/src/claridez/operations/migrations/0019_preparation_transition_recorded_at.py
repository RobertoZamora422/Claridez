"""P15: evidencia de conocimiento prospectiva; no fabrica historia para transiciones legacy."""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0018_incident_follow_up_integrity")]

    operations = [
        migrations.AddField(
            model_name="preparationtransition",
            name="recorded_at",
            field=models.DateTimeField(null=True, editable=False),
        ),
        migrations.AlterField(
            model_name="preparationtransition",
            name="recorded_at",
            field=models.DateTimeField(
                null=True, default=django.utils.timezone.now, editable=False
            ),
        ),
        migrations.RunSQL(
            """
            CREATE FUNCTION public.operations_capture_transition_recorded_at()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                NEW.recorded_at := clock_timestamp();
                RETURN NEW;
            END;
            $function$;
            CREATE TRIGGER operations_transition_recorded_at
            BEFORE INSERT ON public.operations_preparationtransition
            FOR EACH ROW EXECUTE FUNCTION public.operations_capture_transition_recorded_at();
            """,
            """
            DROP TRIGGER operations_transition_recorded_at
                ON public.operations_preparationtransition;
            DROP FUNCTION public.operations_capture_transition_recorded_at();
            """,
        ),
    ]
