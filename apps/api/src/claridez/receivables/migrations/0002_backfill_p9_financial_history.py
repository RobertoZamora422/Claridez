from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db import migrations

NAMESPACE = uuid.UUID("f180fcbe-5713-51dd-9a37-a7bd4234daf9")


def _id(kind: str, organization_id: uuid.UUID, source_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{organization_id}:{source_id}")


def _backfill_organization(apps: Any, organization_id: Any) -> None:
    Reservation = apps.get_model("scheduling", "Reservation")
    ScheduleEvent = apps.get_model("scheduling", "ScheduleEvent")
    QuotationVersion = apps.get_model("commercial", "QuotationVersion")
    ReceivableObligation = apps.get_model("receivables", "ReceivableObligation")
    ReceivedPayment = apps.get_model("receivables", "ReceivedPayment")
    PaymentApplication = apps.get_model("receivables", "PaymentApplication")
    FinancialEvent = apps.get_model("receivables", "FinancialEvent")
    LegacyEvidenceReview = apps.get_model("receivables", "LegacyEvidenceReview")

    sources = tuple(
        Reservation.objects.filter(
            organization_id=organization_id,
            confirmation_source_id__isnull=False,
        )
        .order_by("root_id", "confirmation_source_id")
        .values_list("root_id", "confirmation_source_id")
        .distinct()
    )
    for root_id, confirmation_source_id in sources:
        source = Reservation.objects.filter(
            organization_id=organization_id,
            pk=confirmation_source_id,
            root_id=root_id,
        ).first()
        if source is None:
            raise RuntimeError(f"P10 preflight: confirmation source missing for root {root_id}.")
        if source.confirmed_at is None or source.confirmed_by_membership_id is None:
            raise RuntimeError(
                f"P10 preflight: confirmation actor/time missing for root {root_id}."
            )
        quote = (
            QuotationVersion.objects.select_related("quotation", "quotation__event_request")
            .filter(
                organization_id=organization_id,
                pk=source.quotation_version_id,
                status="accepted",
                accepted_at__isnull=False,
            )
            .first()
        )
        if quote is None:
            raise RuntimeError(f"P10 preflight: accepted quotation missing for root {root_id}.")
        if quote.quotation.event_request_id != source.event_request_id:
            raise RuntimeError(f"P10 preflight: quotation/request mismatch for root {root_id}.")
        if (
            Reservation.objects.filter(organization_id=organization_id, root_id=root_id)
            .exclude(
                event_request_id=source.event_request_id,
                quotation_version_id=source.quotation_version_id,
            )
            .exists()
        ):
            raise RuntimeError(f"P10 preflight: divergent reservation chain for root {root_id}.")
        confirmation_event = ScheduleEvent.objects.filter(
            organization_id=organization_id,
            reservation_id=confirmation_source_id,
            kind="reservation_confirmed",
        ).first()
        if confirmation_event is None:
            confirmation_event = ScheduleEvent.objects.filter(
                organization_id=organization_id,
                event_request_id=source.event_request_id,
                root_reservation_id=root_id,
                reservation_id=confirmation_source_id,
                kind="cutover_snapshot",
                source="cutover",
                new_snapshot__status__in=["confirmed", "cancelled", "rescheduled"],
                new_snapshot__reservation_id=str(confirmation_source_id),
                new_snapshot__root_id=str(root_id),
            ).first()
        if confirmation_event is None:
            raise RuntimeError(f"P10 preflight: confirmation event missing for root {root_id}.")
        obligation_defaults = {
            "id": _id("obligation", organization_id, root_id),
            "confirmation_source_id": confirmation_source_id,
            "confirmation_event_id": confirmation_event.pk,
            "event_request_id": source.event_request_id,
            "quotation_version_id": quote.pk,
            "quotation_visible_number": quote.quotation.visible_number,
            "quotation_version": quote.version,
            "counterparty_person_id": quote.quotation.event_request.person_id,
            "counterparty_name_snapshot": quote.person_name_snapshot,
            "currency": quote.currency,
            "subtotal": quote.subtotal,
            "discount_total": quote.discount_total,
            "original_total": quote.total,
            "economic_terms_snapshot": {
                "quotation_notes": quote.notes,
                "accepted_at": quote.accepted_at.isoformat(),
                "provenance": "p9_to_p10_backfill",
            },
            "confirmed_at": source.confirmed_at,
            "created_by_membership_id": source.confirmed_by_membership_id,
        }
        obligation, obligation_created = ReceivableObligation.objects.get_or_create(
            organization_id=organization_id,
            root_reservation_id=root_id,
            defaults=obligation_defaults,
        )
        obligation_mismatch = any(
            getattr(obligation, field) != value
            for field, value in obligation_defaults.items()
            if field not in {"id", "economic_terms_snapshot", "confirmation_event_id"}
        )
        if obligation_mismatch:
            raise RuntimeError(f"P10 preflight: existing obligation conflicts with root {root_id}.")
        if obligation.confirmation_event_id != confirmation_event.pk:
            previous_event_exists = ScheduleEvent.objects.filter(
                organization_id=organization_id,
                pk=obligation.confirmation_event_id,
            ).exists()
            if previous_event_exists:
                raise RuntimeError(
                    f"P10 preflight: obligation event conflicts with root {root_id}."
                )
            obligation.confirmation_event_id = confirmation_event.pk
            obligation.save(update_fields=["confirmation_event_id"])
        if obligation_created:
            FinancialEvent.objects.create(
                id=_id("obligation_event", organization_id, root_id),
                organization_id=organization_id,
                kind="obligation_backfilled",
                aggregate_type="obligation",
                aggregate_id=obligation.pk,
                actor_membership_id=source.confirmed_by_membership_id,
                payload={"provenance": "p9_to_p10_backfill"},
                occurred_at=source.confirmed_at,
            )
        if source.confirmation_kind == "waiver":
            continue
        coherent_deposit = (
            source.confirmation_kind == "external_deposit"
            and source.recognized_deposit_amount is not None
            and source.recognized_deposit_amount > Decimal("0.00")
            and source.recognized_deposit_amount <= quote.total
            and source.deposit_reported_at is not None
        )
        if not coherent_deposit:
            LegacyEvidenceReview.objects.get_or_create(
                organization_id=organization_id,
                confirmation_source_id=confirmation_source_id,
                defaults={
                    "id": _id("review", organization_id, confirmation_source_id),
                    "root_reservation_id": root_id,
                    "classification": "not_converted",
                    "reason": "La constancia 5.1 no contiene evidencia coherente suficiente.",
                    "source_snapshot": {
                        "confirmation_kind": source.confirmation_kind,
                        "recognized_deposit_amount": (
                            str(source.recognized_deposit_amount)
                            if source.recognized_deposit_amount is not None
                            else None
                        ),
                        "deposit_reported_at": (
                            source.deposit_reported_at.isoformat()
                            if source.deposit_reported_at is not None
                            else None
                        ),
                        "reference": source.deposit_reference,
                    },
                },
            )
            continue
        payment = ReceivedPayment.objects.filter(
            organization_id=organization_id,
            confirmation_source_id=confirmation_source_id,
        ).first()
        if payment is not None:
            payment_mismatch = (
                payment.root_reservation_id != root_id
                or payment.event_request_id != source.event_request_id
                or payment.counterparty_person_id != quote.quotation.event_request.person_id
                or payment.amount != source.recognized_deposit_amount
                or payment.currency != quote.currency
                or payment.reported_at != source.deposit_reported_at
                or payment.recorded_by_membership_id != source.confirmed_by_membership_id
            )
            if payment_mismatch:
                raise RuntimeError(
                    "P10 preflight: existing payment conflicts with source "
                    f"{confirmation_source_id}."
                )
            application = PaymentApplication.objects.filter(
                organization_id=organization_id,
                payment_id=payment.pk,
                obligation_id=obligation.pk,
                amount=source.recognized_deposit_amount,
                currency=quote.currency,
            ).first()
            if application is None:
                raise RuntimeError(
                    "P10 preflight: existing confirmation payment lacks its canonical application."
                )
            continue
        payment = ReceivedPayment.objects.create(
            id=_id("payment", organization_id, confirmation_source_id),
            organization_id=organization_id,
            root_reservation_id=root_id,
            event_request_id=source.event_request_id,
            counterparty_person_id=quote.quotation.event_request.person_id,
            amount=source.recognized_deposit_amount,
            currency=quote.currency,
            reported_at=source.deposit_reported_at,
            method="legacy_unspecified",
            reference=source.deposit_reference,
            normalized_reference=" ".join(source.deposit_reference.strip().casefold().split()),
            observation=(
                "Pago recibido externamente declarado por un usuario interno de la organización."
            ),
            provenance="legacy_5_1_confirmation",
            evidence_level="internal_report",
            confirmation_source_id=confirmation_source_id,
            recorded_by_membership_id=source.confirmed_by_membership_id,
            possible_duplicate=False,
            duplicate_review_note="",
        )
        application = PaymentApplication.objects.create(
            id=_id("application", organization_id, confirmation_source_id),
            organization_id=organization_id,
            payment=payment,
            obligation=obligation,
            due_key=None,
            amount=source.recognized_deposit_amount,
            currency=quote.currency,
            applied_by_membership_id=source.confirmed_by_membership_id,
            applied_at=source.confirmed_at,
        )
        FinancialEvent.objects.bulk_create(
            [
                FinancialEvent(
                    id=_id("payment_event", organization_id, confirmation_source_id),
                    organization_id=organization_id,
                    kind="payment_backfilled",
                    aggregate_type="payment",
                    aggregate_id=payment.pk,
                    actor_membership_id=source.confirmed_by_membership_id,
                    payload={
                        "provenance": "legacy_5_1_confirmation",
                        "evidence_level": "internal_report",
                    },
                    occurred_at=source.deposit_reported_at,
                ),
                FinancialEvent(
                    id=_id("application_event", organization_id, confirmation_source_id),
                    organization_id=organization_id,
                    kind="application_backfilled",
                    aggregate_type="application",
                    aggregate_id=application.pk,
                    actor_membership_id=source.confirmed_by_membership_id,
                    payload={"provenance": "legacy_5_1_confirmation"},
                    occurred_at=source.confirmed_at,
                ),
            ]
        )

    if ReceivableObligation.objects.filter(organization_id=organization_id).count() != len(sources):
        raise RuntimeError(
            "P10 verification: obligation cardinality does not match confirmed roots."
        )
    converted_sources = ReceivedPayment.objects.filter(
        organization_id=organization_id,
        provenance="legacy_5_1_confirmation",
    ).count()
    if (
        PaymentApplication.objects.filter(
            organization_id=organization_id,
            payment__provenance="legacy_5_1_confirmation",
        ).count()
        != converted_sources
    ):
        raise RuntimeError("P10 verification: legacy payment/application cardinality mismatch.")


def backfill_financial_history(apps: Any, schema_editor: Any) -> None:
    Organization = apps.get_model("organizations", "Organization")
    organization_ids = tuple(Organization.objects.order_by("id").values_list("id", flat=True))
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        previous = cursor.fetchone()[0]
        try:
            for organization_id in organization_ids:
                cursor.execute(
                    "SELECT set_config('claridez.organization_id', %s, true)",
                    (str(organization_id),),
                )
                _backfill_organization(apps, organization_id)
        finally:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, true)",
                (previous or "",),
            )


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0008_delete_reservation"),
        ("scheduling", "0009_allow_terminal_operational_successors"),
        ("receivables", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill_financial_history, migrations.RunPython.noop)]
