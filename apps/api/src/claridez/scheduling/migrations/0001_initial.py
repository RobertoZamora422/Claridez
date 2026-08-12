import uuid

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models

ADOPT_RESERVATION_SQL = r"""
LOCK TABLE public.commercial_reservation IN SHARE ROW EXCLUSIVE MODE;

DO $preflight$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.commercial_reservation AS reservation
        LEFT JOIN public.commercial_quotationversion AS version
          ON version.organization_id = reservation.organization_id
         AND version.id = reservation.quotation_version_id
        LEFT JOIN public.commercial_quotation AS quotation
          ON quotation.organization_id = version.organization_id
         AND quotation.id = version.quotation_id
        WHERE reservation.event_interval IS NULL
           OR isempty(reservation.event_interval)
           OR lower_inf(reservation.event_interval)
           OR upper_inf(reservation.event_interval)
           OR lower_inc(reservation.event_interval) IS NOT TRUE
           OR upper_inc(reservation.event_interval) IS TRUE
           OR lower(reservation.event_interval) >= upper(reservation.event_interval)
           OR btrim(reservation.event_timezone) = ''
           OR version.id IS NULL
           OR version.status <> 'accepted'
           OR quotation.event_request_id <> reservation.event_request_id
    ) THEN
        RAISE EXCEPTION 'P8 preflight: reservation evidence or interval is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT organization_id, event_request_id
        FROM public.commercial_reservation
        WHERE status IN ('provisional', 'confirmed')
        GROUP BY organization_id, event_request_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'P8 preflight: multiple active reservations for event request'
            USING ERRCODE = '23514';
    END IF;
END
$preflight$;

ALTER TABLE public.commercial_reservation
    DROP CONSTRAINT IF EXISTS commercial_reservation_no_overlap,
    DROP CONSTRAINT IF EXISTS commercial_reservation_org_quoteversion_uq,
    DROP CONSTRAINT IF EXISTS commercial_reservation_quotation_version_id_key,
    DROP CONSTRAINT IF EXISTS commercial_reservation_status_valid,
    ADD COLUMN root_id uuid,
    ADD COLUMN predecessor_id uuid,
    ADD COLUMN confirmation_source_id uuid,
    ADD COLUMN setup_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN teardown_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN buffer_before_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN buffer_after_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN revision integer NOT NULL DEFAULT 1;

ALTER TABLE public.commercial_reservation
    DISABLE TRIGGER commercial_reservation_transition;
DO $backfill$
DECLARE
    target_organization uuid;
BEGIN
    FOR target_organization IN
        SELECT id FROM public.organizations_organization ORDER BY id
    LOOP
        PERFORM pg_catalog.set_config(
            'claridez.organization_id', target_organization::text, true
        );
        UPDATE public.commercial_reservation
        SET root_id = id,
            confirmation_source_id = CASE WHEN confirmed_at IS NOT NULL THEN id ELSE NULL END
        WHERE organization_id = target_organization;
    END LOOP;
    PERFORM pg_catalog.set_config('claridez.organization_id', '', true);
END
$backfill$;
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE public.commercial_reservation
    ENABLE TRIGGER commercial_reservation_transition;
"""

REVERSE_ADOPTION_SQL = r"""
DO $reverse_preflight$
DECLARE
    has_blocks boolean := false;
BEGIN
    IF pg_catalog.to_regclass('public.scheduling_scheduleblock') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.scheduling_scheduleblock)'
        INTO has_blocks;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.commercial_reservation
        WHERE predecessor_id IS NOT NULL
           OR root_id <> id
           OR setup_minutes <> 0
           OR teardown_minutes <> 0
           OR buffer_before_minutes <> 0
           OR buffer_after_minutes <> 0
           OR status = 'rescheduled'
    ) OR has_blocks THEN
        RAISE EXCEPTION
            'P8 rollback requires restore from the rehearsed backup once P8 traffic exists'
            USING ERRCODE = '23514';
    END IF;
END
$reverse_preflight$;

ALTER TABLE public.commercial_reservation
    DROP COLUMN revision,
    DROP COLUMN buffer_after_minutes,
    DROP COLUMN buffer_before_minutes,
    DROP COLUMN teardown_minutes,
    DROP COLUMN setup_minutes,
    DROP COLUMN confirmation_source_id,
    DROP COLUMN predecessor_id,
    DROP COLUMN root_id;

ALTER TABLE public.commercial_reservation
    ADD CONSTRAINT commercial_reservation_quotation_version_id_key
        UNIQUE (quotation_version_id),
    ADD CONSTRAINT commercial_reservation_org_quoteversion_uq
        UNIQUE (organization_id, quotation_version_id),
    ADD CONSTRAINT commercial_reservation_status_valid
        CHECK (status IN ('provisional', 'confirmed', 'expired', 'cancelled')),
    ADD CONSTRAINT commercial_reservation_no_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            space_id WITH =,
            event_interval WITH &&
        ) WHERE (status IN ('provisional', 'confirmed'));
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("commercial", "0007_remove_reservation_cancelled_by_membership_and_more"),
        ("organizations", "0004_venues_and_spaces"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Reservation",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        (
                            "event_interval",
                            django.contrib.postgres.fields.ranges.DateTimeRangeField(),
                        ),
                        ("event_timezone", models.CharField(max_length=64)),
                        ("setup_minutes", models.PositiveIntegerField(default=0)),
                        ("teardown_minutes", models.PositiveIntegerField(default=0)),
                        ("buffer_before_minutes", models.PositiveIntegerField(default=0)),
                        ("buffer_after_minutes", models.PositiveIntegerField(default=0)),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("provisional", "Provisional"),
                                    ("confirmed", "Confirmada"),
                                    ("expired", "Vencida"),
                                    ("cancelled", "Cancelada"),
                                    ("rescheduled", "Reprogramada"),
                                ],
                                default="provisional",
                                max_length=16,
                            ),
                        ),
                        ("revision", models.PositiveIntegerField(default=1)),
                        ("hold_expires_at", models.DateTimeField()),
                        (
                            "confirmation_kind",
                            models.CharField(
                                blank=True,
                                choices=[
                                    ("external_deposit", "Anticipo recibido externamente"),
                                    ("waiver", "Excepción autorizada"),
                                ],
                                max_length=24,
                            ),
                        ),
                        (
                            "recognized_deposit_amount",
                            models.DecimalField(
                                blank=True, decimal_places=2, max_digits=18, null=True
                            ),
                        ),
                        ("deposit_reported_at", models.DateTimeField(blank=True, null=True)),
                        ("deposit_reference", models.CharField(blank=True, max_length=300)),
                        ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                        ("waiver_reason", models.CharField(blank=True, max_length=500)),
                        ("waiver_authorized_at", models.DateTimeField(blank=True, null=True)),
                        ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                        ("cancellation_reason", models.CharField(blank=True, max_length=500)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "cancelled_by_membership",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="cancelled_reservations",
                                to="organizations.membership",
                            ),
                        ),
                        (
                            "confirmation_source",
                            models.ForeignKey(
                                blank=True,
                                db_constraint=False,
                                db_index=False,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="confirmation_successors",
                                to="scheduling.reservation",
                            ),
                        ),
                        (
                            "confirmed_by_membership",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="confirmed_reservations",
                                to="organizations.membership",
                            ),
                        ),
                        (
                            "event_request",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="reservations",
                                to="commercial.eventrequest",
                            ),
                        ),
                        (
                            "organization",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="organizations.organization",
                            ),
                        ),
                        (
                            "predecessor",
                            models.OneToOneField(
                                blank=True,
                                db_constraint=False,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="successor",
                                to="scheduling.reservation",
                            ),
                        ),
                        (
                            "quotation_version",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="reservation",
                                to="commercial.quotationversion",
                            ),
                        ),
                        (
                            "root",
                            models.ForeignKey(
                                db_constraint=False,
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="chain_members",
                                to="scheduling.reservation",
                            ),
                        ),
                        (
                            "space",
                            models.ForeignKey(
                                db_index=False,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="reservations",
                                to="organizations.space",
                            ),
                        ),
                        (
                            "waiver_authorized_by_membership",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="waived_reservation_deposits",
                                to="organizations.membership",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "commercial_reservation",
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(ADOPT_RESERVATION_SQL, REVERSE_ADOPTION_SQL),
            ],
        ),
        migrations.CreateModel(
            name="ScheduleBlock",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "scope",
                    models.CharField(
                        choices=[("spaces", "Espacios seleccionados"), ("venue", "Sede completa")],
                        max_length=8,
                    ),
                ),
                ("blocked_interval", django.contrib.postgres.fields.ranges.DateTimeRangeField()),
                ("event_timezone", models.CharField(max_length=64)),
                ("reason", models.CharField(max_length=500)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Activo"),
                            ("released", "Liberado"),
                            ("cancelled", "Cancelado"),
                        ],
                        default="active",
                        max_length=12,
                    ),
                ),
                ("revision", models.PositiveIntegerField(default=1)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("termination_reason", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_schedule_blocks",
                        to="organizations.membership",
                    ),
                ),
                (
                    "ended_by_membership",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ended_schedule_blocks",
                        to="organizations.membership",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "venue",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_blocks",
                        to="organizations.venue",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ScheduleBlockTarget",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "block",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="targets",
                        to="scheduling.scheduleblock",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "space",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_block_targets",
                        to="organizations.space",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ScheduleEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("cutover_snapshot", "Snapshot de cutover"),
                            ("reservation_hold_created", "Hold creado"),
                            ("reservation_confirmed", "Reserva confirmada"),
                            ("reservation_expired", "Hold vencido"),
                            ("reservation_rescheduled", "Reserva reprogramada"),
                            ("reservation_cancelled", "Reserva cancelada"),
                            ("block_created", "Bloqueo creado"),
                            ("block_released", "Bloqueo liberado"),
                            ("block_cancelled", "Bloqueo cancelado"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("user", "Usuario"),
                            ("database_expiration", "Expiración de base de datos"),
                            ("cutover", "Cutover"),
                        ],
                        max_length=24,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("aggregate_revision", models.PositiveIntegerField()),
                ("previous_snapshot", models.JSONField(default=dict)),
                ("new_snapshot", models.JSONField(default=dict)),
                ("idempotency_key", models.UUIDField()),
                ("payload_hash", models.CharField(max_length=64)),
                ("occurred_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor_membership",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_events",
                        to="organizations.membership",
                    ),
                ),
                (
                    "block",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_events",
                        to="scheduling.scheduleblock",
                    ),
                ),
                (
                    "event_request",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_events",
                        to="commercial.eventrequest",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "predecessor",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="predecessor_schedule_events",
                        to="scheduling.reservation",
                    ),
                ),
                (
                    "reservation",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_events",
                        to="scheduling.reservation",
                    ),
                ),
                (
                    "root_reservation",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="root_schedule_events",
                        to="scheduling.reservation",
                    ),
                ),
                (
                    "successor",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="successor_schedule_events",
                        to="scheduling.reservation",
                    ),
                ),
            ],
            options={
                "ordering": ["occurred_at", "recorded_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="ScheduleAllocation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("occupied_interval", django.contrib.postgres.fields.ranges.DateTimeRangeField()),
                ("source_revision", models.PositiveIntegerField()),
                ("is_blocking", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "reservation",
                    models.OneToOneField(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocation",
                        to="scheduling.reservation",
                    ),
                ),
                (
                    "space",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="schedule_allocations",
                        to="organizations.space",
                    ),
                ),
                (
                    "block_target",
                    models.OneToOneField(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocation",
                        to="scheduling.scheduleblocktarget",
                    ),
                ),
                (
                    "source_event",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocations",
                        to="scheduling.scheduleevent",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="SpaceSchedulePolicy",
            fields=[
                (
                    "space",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        related_name="schedule_policy",
                        serialize=False,
                        to="organizations.space",
                    ),
                ),
                ("setup_minutes", models.PositiveIntegerField(default=0)),
                ("teardown_minutes", models.PositiveIntegerField(default=0)),
                ("buffer_before_minutes", models.PositiveIntegerField(default=0)),
                ("buffer_after_minutes", models.PositiveIntegerField(default=0)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="reservation",
            index=models.Index(
                fields=["organization", "root", "created_at", "id"],
                name="scheduling_res_root_chain_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="reservation",
            index=models.Index(
                fields=["organization", "event_request", "status"],
                name="scheduling_res_request_idx",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="reservation",
                    constraint=models.UniqueConstraint(
                        fields=("organization", "id"), name="commercial_reservation_org_id_uq"
                    ),
                )
            ],
            database_operations=[],
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("predecessor__isnull", True)),
                fields=("organization", "quotation_version"),
                name="scheduling_reservation_quote_root_uq",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="reservation",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("status__in", ["provisional", "confirmed"])),
                        fields=("organization", "event_request"),
                        name="commercial_reservation_one_active_request_uq",
                    ),
                )
            ],
            database_operations=[],
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["provisional", "confirmed"])),
                fields=("organization", "root"),
                name="scheduling_reservation_one_active_root_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "status__in",
                        ["provisional", "confirmed", "expired", "cancelled", "rescheduled"],
                    )
                ),
                name="commercial_reservation_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=models.CheckConstraint(
                condition=models.Q(("revision__gte", 1)),
                name="scheduling_reservation_revision_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("predecessor__isnull", True), ("root", models.F("id"))),
                    models.Q(
                        ("predecessor__isnull", False),
                        models.Q(("root", models.F("id")), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="scheduling_reservation_root_shape",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="reservation",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            ("recognized_deposit_amount__isnull", True),
                            ("recognized_deposit_amount__gt", 0),
                            _connector="OR",
                        ),
                        name="commercial_reservation_deposit_positive",
                    ),
                )
            ],
            database_operations=[],
        ),
        migrations.AddIndex(
            model_name="scheduleblock",
            index=models.Index(
                fields=["organization", "venue", "status"], name="scheduling_block_venue_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblock",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="scheduling_block_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblock",
            constraint=models.CheckConstraint(
                condition=models.Q(("scope__in", ["spaces", "venue"])),
                name="scheduling_block_scope_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblock",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["active", "released", "cancelled"])),
                name="scheduling_block_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblock",
            constraint=models.CheckConstraint(
                condition=models.Q(("revision__gte", 1)), name="scheduling_block_revision_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblock",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("reason", django.db.models.functions.text.Trim("reason")),
                    models.Q(("reason", ""), _negated=True),
                ),
                name="scheduling_block_reason_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblock",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("ended_at__isnull", True),
                        ("ended_by_membership__isnull", True),
                        ("status", "active"),
                        ("termination_reason", ""),
                    ),
                    models.Q(
                        ("ended_at__isnull", False),
                        ("ended_by_membership__isnull", False),
                        ("status__in", ["released", "cancelled"]),
                        models.Q(("termination_reason", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="scheduling_block_termination_evidence",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblocktarget",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="scheduling_blocktarget_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleblocktarget",
            constraint=models.UniqueConstraint(
                fields=("organization", "block", "space"),
                name="scheduling_blocktarget_org_block_space_uq",
            ),
        ),
        migrations.AddIndex(
            model_name="scheduleevent",
            index=models.Index(
                fields=["organization", "event_request", "occurred_at"],
                name="scheduling_event_request_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="scheduleevent",
            index=models.Index(
                fields=["organization", "root_reservation", "occurred_at"],
                name="scheduling_event_root_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleevent",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="scheduling_event_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleevent",
            constraint=models.UniqueConstraint(
                fields=("organization", "kind", "idempotency_key"),
                name="scheduling_event_idempotency_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("aggregate_revision__gte", 1)),
                name="scheduling_event_revision_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("actor_membership__isnull", False), ("source", "user")),
                    models.Q(
                        ("actor_membership__isnull", True),
                        ("source__in", ["database_expiration", "cutover"]),
                    ),
                    _connector="OR",
                ),
                name="scheduling_event_actor_source",
            ),
        ),
        migrations.AddIndex(
            model_name="scheduleallocation",
            index=models.Index(
                fields=["organization", "space", "is_blocking"], name="scheduling_alloc_space_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleallocation",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="scheduling_allocation_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("block_target__isnull", True), ("reservation__isnull", False)),
                    models.Q(("block_target__isnull", False), ("reservation__isnull", True)),
                    _connector="OR",
                ),
                name="scheduling_allocation_one_origin",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(("source_revision__gte", 1)),
                name="scheduling_allocation_revision_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleallocation",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("is_blocking", True)),
                expressions=[("organization", "="), ("space", "="), ("occupied_interval", "&&")],
                name="scheduling_allocation_no_overlap",
            ),
        ),
        migrations.AddConstraint(
            model_name="spaceschedulepolicy",
            constraint=models.UniqueConstraint(
                fields=("organization", "space"), name="scheduling_policy_org_space_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="spaceschedulepolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(("revision__gte", 1)), name="scheduling_policy_revision_positive"
            ),
        ),
    ]
