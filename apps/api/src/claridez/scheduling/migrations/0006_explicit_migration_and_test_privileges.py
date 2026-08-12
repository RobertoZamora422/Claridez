from django.db import migrations

FORWARD_SQL = r"""
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.scheduling_spaceschedulepolicy,
    public.scheduling_scheduleblock,
    public.scheduling_scheduleblocktarget,
    public.scheduling_scheduleevent,
    public.scheduling_scheduleallocation
TO claridez_migrator, claridez_test_runner;
"""


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0005_allow_quotation_reservation_chains")]

    # Los grants deben seguir vigentes mientras las migraciones anteriores revierten las tablas.
    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
