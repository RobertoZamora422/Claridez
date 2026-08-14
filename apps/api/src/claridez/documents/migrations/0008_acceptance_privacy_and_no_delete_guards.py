from django.db import migrations, models

DOCUMENT_TABLES = (
    "documents_documenttemplate",
    "documents_documenttemplateversion",
    "documents_templateevent",
    "documents_contractualrecord",
    "documents_contractualinstrument",
    "documents_issuedinstrumentversion",
    "documents_generatedartifact",
    "documents_artifactintegrityevent",
    "documents_externalfile",
    "documents_externalfileevent",
    "documents_malwarescanattempt",
    "documents_externalaccessgrant",
    "documents_externaldocumentsession",
    "documents_acceptancechallenge",
    "documents_acceptanceevidence",
    "documents_externalaccessevent",
    "documents_retentionpolicy",
    "documents_retentionassignment",
    "documents_legalhold",
    "documents_retentionevent",
    "documents_documentjob",
    "documents_documentjobattempt",
)

FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.claridez_documents_no_delete_v4()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
BEGIN
    RAISE EXCEPTION 'documentary physical deletion is not available' USING ERRCODE = '23514';
END
$function$;
REVOKE ALL ON FUNCTION public.claridez_documents_no_delete_v4() FROM PUBLIC;
"""


def _forward_sql() -> str:
    statements = [FUNCTION_SQL]
    for table in DOCUMENT_TABLES:
        statements.extend(
            (
                f"DROP TRIGGER IF EXISTS {table}_no_delete ON public.{table};",
                (
                    f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON public.{table} "
                    "FOR EACH ROW EXECUTE FUNCTION public.claridez_documents_no_delete_v4();"
                ),
            )
        )
    return "\n".join(statements)


def _reverse_sql() -> str:
    statements = [
        f"DROP TRIGGER IF EXISTS {table}_no_delete ON public.{table};"
        for table in reversed(DOCUMENT_TABLES)
    ]
    statements.append("DROP FUNCTION IF EXISTS public.claridez_documents_no_delete_v4();")
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("documents", "0007_external_file_integrity_state")]

    operations = [
        migrations.AlterField(
            model_name="acceptanceevidence",
            name="user_agent",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.RunSQL(_forward_sql(), _reverse_sql()),
    ]
