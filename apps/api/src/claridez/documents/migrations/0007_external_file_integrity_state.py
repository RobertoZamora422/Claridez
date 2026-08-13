from django.db import migrations, models

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_guard_external_file_v3()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF ROW(NEW.organization_id, NEW.record_id, NEW.display_name, NEW.storage_key,
           NEW.declared_media_type, NEW.detected_media_type, NEW.extension,
           NEW.sha256, NEW.size_bytes, NEW.uploaded_by_membership_id, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.organization_id, OLD.record_id, OLD.display_name, OLD.storage_key,
           OLD.declared_media_type, OLD.detected_media_type, OLD.extension,
           OLD.sha256, OLD.size_bytes, OLD.uploaded_by_membership_id, OLD.created_at) THEN
        RAISE EXCEPTION 'external file evidence is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.state IN ('infected', 'rejected', 'integrity_failed') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'terminal external files are immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.state <> OLD.state AND NOT (
        (OLD.state = 'uploading' AND NEW.state IN ('quarantined', 'rejected')) OR
        (OLD.state = 'quarantined' AND NEW.state = 'pending_scan') OR
        (OLD.state IN ('pending_scan', 'scan_error') AND
         NEW.state IN ('clean', 'infected', 'rejected', 'scan_error')) OR
        (OLD.state = 'clean' AND NEW.state = 'integrity_failed')
    ) THEN
        RAISE EXCEPTION 'invalid external file transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_external_file_v3() FROM PUBLIC;
DROP TRIGGER IF EXISTS documents_externalfile_guard ON public.documents_externalfile;
CREATE TRIGGER documents_externalfile_guard BEFORE UPDATE ON public.documents_externalfile
    FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_external_file_v3();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS documents_externalfile_guard ON public.documents_externalfile;
CREATE TRIGGER documents_externalfile_guard BEFORE UPDATE ON public.documents_externalfile
    FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_external_file_v2();
DROP FUNCTION IF EXISTS public.claridez_guard_external_file_v3();
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0006_state_and_identity_guards")]

    operations = [
        migrations.AlterField(
            model_name="externalfile",
            name="state",
            field=models.CharField(
                choices=[
                    ("uploading", "Subiendo"),
                    ("quarantined", "En cuarentena"),
                    ("pending_scan", "Pendiente de análisis"),
                    ("clean", "Limpio"),
                    ("infected", "Infectado"),
                    ("rejected", "Rechazado"),
                    ("scan_error", "Error de análisis"),
                    ("integrity_failed", "Integridad fallida"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="externalfileevent",
            name="to_state",
            field=models.CharField(
                choices=[
                    ("uploading", "Subiendo"),
                    ("quarantined", "En cuarentena"),
                    ("pending_scan", "Pendiente de análisis"),
                    ("clean", "Limpio"),
                    ("infected", "Infectado"),
                    ("rejected", "Rechazado"),
                    ("scan_error", "Error de análisis"),
                    ("integrity_failed", "Integridad fallida"),
                ],
                max_length=20,
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
