from django.db import migrations

INTEGRITY_SQL = r"""
ALTER TABLE communications_communicationoutbox
ADD CONSTRAINT communications_outbox_org_message_fk
FOREIGN KEY (organization_id, message_id)
REFERENCES communications_logicalmessage(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_communicationoutbox
ADD CONSTRAINT communications_outbox_org_id_message_uq
UNIQUE (organization_id, id, message_id);

ALTER TABLE communications_deliveryattempt
ADD CONSTRAINT communications_attempt_org_outbox_message_fk
FOREIGN KEY (organization_id, outbox_id, message_id)
REFERENCES communications_communicationoutbox(organization_id, id, message_id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE communications_providerevent
ADD CONSTRAINT communications_event_org_message_fk
FOREIGN KEY (organization_id, message_id)
REFERENCES communications_logicalmessage(organization_id, id)
DEFERRABLE INITIALLY DEFERRED;
"""

REVERSE_INTEGRITY_SQL = r"""
ALTER TABLE communications_deliveryattempt
DROP CONSTRAINT IF EXISTS communications_attempt_org_outbox_message_fk;

ALTER TABLE communications_communicationoutbox
DROP CONSTRAINT IF EXISTS communications_outbox_org_message_fk;

ALTER TABLE communications_providerevent
DROP CONSTRAINT IF EXISTS communications_event_org_message_fk;

ALTER TABLE communications_communicationoutbox
DROP CONSTRAINT IF EXISTS communications_outbox_org_id_message_uq;
"""


class Migration(migrations.Migration):
    dependencies = [("communications", "0002_tenant_security")]
    operations = [
        migrations.RunSQL(INTEGRITY_SQL, reverse_sql=REVERSE_INTEGRITY_SQL),
    ]
