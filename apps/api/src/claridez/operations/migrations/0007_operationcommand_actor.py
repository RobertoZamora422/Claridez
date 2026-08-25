import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0006_p13_integrity"),
        ("organizations", "0004_venues_and_spaces"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationcommand",
            name="actor_membership",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="advanced_operation_commands",
                to="organizations.membership",
            ),
        ),
        migrations.RunSQL(
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.operations_operationcommand
                    WHERE actor_membership_id IS NULL
                ) THEN
                    RAISE EXCEPTION 'P13 command history without actor cannot be invented'
                        USING ERRCODE = '23514';
                END IF;
            END $$;
            """,
            migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="operationcommand",
            name="actor_membership",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="advanced_operation_commands",
                to="organizations.membership",
            ),
        ),
        migrations.RunSQL(
            """
            ALTER TABLE public.operations_operationcommand
            ADD CONSTRAINT op13_command_actor_fk
            FOREIGN KEY (organization_id, actor_membership_id)
            REFERENCES public.organizations_membership (organization_id, id)
            DEFERRABLE INITIALLY DEFERRED;
            """,
            """
            ALTER TABLE public.operations_operationcommand
            DROP CONSTRAINT IF EXISTS op13_command_actor_fk;
            """,
        ),
    ]
