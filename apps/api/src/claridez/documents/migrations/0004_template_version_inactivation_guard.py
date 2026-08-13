from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_guard_template_version_v2()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    IF ROW(NEW.organization_id, NEW.template_id, NEW.version, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.organization_id, OLD.template_id, OLD.version, OLD.created_at) THEN
        RAISE EXCEPTION 'template version identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'draft' THEN
        IF NEW.status NOT IN ('draft', 'published') THEN
            RAISE EXCEPTION 'invalid draft transition' USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'published' THEN
        IF NEW.status <> 'inactive' OR
           ROW(NEW.title, NEW.body_html, NEW.variable_schema,
               NEW.variable_language_version, NEW.source_sha256,
               NEW.assets_manifest, NEW.assets_sha256, NEW.published_at,
               NEW.published_by_membership_id)
           IS DISTINCT FROM
           ROW(OLD.title, OLD.body_html, OLD.variable_schema,
               OLD.variable_language_version, OLD.source_sha256,
               OLD.assets_manifest, OLD.assets_sha256, OLD.published_at,
               OLD.published_by_membership_id) THEN
            RAISE EXCEPTION 'published template content is immutable' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'inactive template versions are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_guard_template_version_v2() FROM PUBLIC;
DROP TRIGGER IF EXISTS documents_documenttemplateversion_guard
    ON public.documents_documenttemplateversion;
CREATE TRIGGER documents_documenttemplateversion_guard
    BEFORE UPDATE ON public.documents_documenttemplateversion
    FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_template_version_v2();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS documents_documenttemplateversion_guard
    ON public.documents_documenttemplateversion;
CREATE TRIGGER documents_documenttemplateversion_guard
    BEFORE UPDATE ON public.documents_documenttemplateversion
    FOR EACH ROW EXECUTE FUNCTION public.claridez_guard_document_version();
DROP FUNCTION IF EXISTS public.claridez_guard_template_version_v2();
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_generatedartifact_is_emitted_original_and_more")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
