from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE public.commercial_reservation
    DROP CONSTRAINT IF EXISTS commercial_reservation_quotation_version_id_key;
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0004_projection_and_direct_sql_hardening")]

    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
