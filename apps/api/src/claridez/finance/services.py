from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Max, Sum
from django.utils import timezone

import claridez.commercial.public as commercial_port
import claridez.operations.public as operations_port
import claridez.organizations.public as organizations_port
import claridez.receivables.public as receivables_port
import claridez.scheduling.public as scheduling_port
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    ActualDirectCost,
    CashMovementCorrection,
    DirectCostCorrection,
    DirectCostPlanLine,
    DirectCostPlanRevision,
    EvidenceDecision,
    ExpenseAllocation,
    ExpenseOccurrence,
    ExpenseOccurrenceCorrection,
    FinanceCategory,
    FinanceCommand,
    OperatingBudgetLine,
    OperatingBudgetRevision,
    OperatingCashMovement,
    OperationalCostEvidence,
    OperationalPeriod,
    PeriodCloseSnapshot,
    RecognitionAdjustment,
    RecognitionAdjustmentCorrection,
    RecurringExpenseRule,
)
from .money import amount, currency, json_value, payload_hash, positive_amount

ZERO = Decimal("0.00")
HUNDRED = Decimal("100.00")
AttributionKey = tuple[str, UUID | None, UUID | None]
NormalizedAttribution = tuple[str, UUID | None, UUID | None, Decimal]
FORBIDDEN_RECOGNITION_TERMS = (
    "cancel",
    "penal",
    "anticipo",
    "deposit",
    "credito",
    "crédito",
    "devolu",
    "refund",
)


def _uuid(value: UUID | str, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(label) from None


def _positive(value: Decimal | int | str) -> Decimal:
    try:
        return positive_amount(value)
    except ValueError as error:
        raise invalid(str(error)) from error


def _money_currency(value: str) -> str:
    try:
        return currency(value)
    except ValueError as error:
        raise invalid(str(error)) from error


def _lock(key: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def _command_replay(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
) -> tuple[str, UUID] | None:
    _lock(f"finance:{authorization.organization_id}:command:{command_type}:{idempotency_key}")
    row = FinanceCommand.objects.filter(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
    ).first()
    if row is None:
        return None
    if row.payload_sha256 != payload_hash(payload):
        raise conflict(
            "idempotency_conflict",
            "La clave de idempotencia ya fue usada con una solicitud diferente.",
        )
    return row.result_type, row.result_reference


def _complete_command(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
    result_type: str,
    result_reference: UUID,
) -> None:
    FinanceCommand.objects.create(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
        payload_sha256=payload_hash(payload),
        result_type=result_type,
        result_reference=result_reference,
    )


def _organization(
    authorization: TenantAuthorization,
) -> organizations_port.OrganizationContractualProjection:
    return organizations_port.contractual_organization(authorization.organization_id)


def _organization_currency(authorization: TenantAuthorization, value: str) -> str:
    normalized = _money_currency(value)
    expected = _organization(authorization).currency
    if normalized != expected:
        raise invalid("La moneda debe coincidir con la moneda histórica de la organización.")
    return normalized


def _category(
    authorization: TenantAuthorization,
    category_id: UUID | str,
    *,
    kinds: tuple[str, ...] = (),
) -> FinanceCategory:
    try:
        row = FinanceCategory.objects.get(
            organization_id=authorization.organization_id,
            pk=_uuid(category_id, "La categoría"),
        )
    except FinanceCategory.DoesNotExist:
        raise unavailable("La categoría") from None
    if kinds and row.kind not in kinds:
        raise invalid("La categoría no corresponde al tipo de hecho.")
    return row


def _period(
    authorization: TenantAuthorization, period_id: UUID | str, *, lock: bool = False
) -> OperationalPeriod:
    normalized_id = _uuid(period_id, "El periodo")
    if lock:
        _lock(f"finance:{authorization.organization_id}:period:{normalized_id}")
    try:
        return OperationalPeriod.objects.get(
            organization_id=authorization.organization_id,
            pk=normalized_id,
        )
    except OperationalPeriod.DoesNotExist:
        raise unavailable("El periodo") from None


def _is_closed(period: OperationalPeriod) -> bool:
    return PeriodCloseSnapshot.objects.filter(
        organization_id=period.organization_id, period_id=period.pk
    ).exists()


def _local_today(authorization: TenantAuthorization) -> date:
    zone = ZoneInfo(_organization(authorization).timezone_name)
    return timezone.now().astimezone(zone).date()


def _period_for_date(authorization: TenantAuthorization, economic_date: date) -> OperationalPeriod:
    try:
        return OperationalPeriod.objects.get(
            organization_id=authorization.organization_id,
            starts_on__lte=economic_date,
            ends_on__gt=economic_date,
        )
    except OperationalPeriod.DoesNotExist:
        raise conflict(
            "economic_period_missing",
            "La fecha económica no pertenece a un periodo operativo configurado.",
        ) from None


def _registration_period(
    authorization: TenantAuthorization, economic_date: date
) -> OperationalPeriod:
    if economic_date > _local_today(authorization):
        raise invalid("La fecha económica de un hecho real no puede estar en el futuro.")
    economic = _period_for_date(authorization, economic_date)
    locked = _period(authorization, economic.pk, lock=True)
    if not _is_closed(locked):
        return locked
    next_open_reference = (
        OperationalPeriod.objects.filter(
            organization_id=authorization.organization_id,
            starts_on__gte=locked.ends_on,
            close_snapshot__isnull=True,
        )
        .order_by("starts_on", "id")
        .first()
    )
    if next_open_reference is None:
        raise conflict(
            "open_registration_period_missing",
            "No existe un periodo posterior abierto para registrar el ajuste tardío.",
        )
    next_open = _period(authorization, next_open_reference.pk, lock=True)
    if _is_closed(next_open):
        raise conflict(
            "open_registration_period_missing",
            "El periodo posterior disponible se cerró durante el registro.",
        )
    return next_open


def _history(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> scheduling_port.RootScheduleHistoryProjection:
    try:
        return scheduling_port.root_schedule_history_for_finance(authorization, root_reservation_id)
    except scheduling_port.SchedulingError:
        raise unavailable("La raíz de reserva") from None


def _validate_root_venue(
    authorization: TenantAuthorization, root_reservation_id: UUID, venue_id: UUID
) -> scheduling_port.RootScheduleHistoryProjection:
    history = _history(authorization, root_reservation_id)
    if venue_id not in {item.venue_id for item in history.reservations}:
        raise conflict(
            "venue_not_in_root_history",
            "La sede no pertenece a la historia económica de la raíz.",
        )
    return history


def _validate_venue(authorization: TenantAuthorization, venue_id: UUID) -> None:
    if organizations_port.venue_for_finance(authorization, venue_id) is None:
        raise unavailable("La sede") from None


def _execution(
    authorization: TenantAuthorization, root_reservation_id: UUID, *, lock: bool = False
) -> operations_port.ExecutionEvidenceProjection | None:
    return operations_port.execution_evidence_for_finance(
        authorization, root_reservation_id, lock=lock
    )


def _sale(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> commercial_port.EconomicSaleProjection:
    obligation = receivables_port.obligation_for_finance(authorization, root_reservation_id)
    sale = commercial_port.economic_sale_for_finance(authorization, obligation.quotation_version_id)
    if sale.currency != obligation.currency or sale.total != obligation.original_total:
        raise conflict(
            "economic_source_mismatch",
            "La proyección económica no coincide con la obligación original.",
        )
    return sale


def finance_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        return tuple(
            sorted(
                capability.value
                for capability in capabilities_for_role(authorization.role)
                if capability.value.startswith("finance:")
            )
        )


def create_category(
    actor: User,
    organization_reference: UUID | str,
    *,
    kind: str,
    name: str,
    idempotency_key: UUID,
) -> FinanceCategory:
    payload = {"kind": kind, "name": name}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_MANAGE_CATEGORIES
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_category",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return _category(authorization, replay[1])
        if kind not in FinanceCategory.Kind.values:
            raise invalid("El tipo de categoría no es válido.")
        clean_name = " ".join(name.split())
        if not clean_name:
            raise invalid("El nombre de la categoría es obligatorio.")
        row = FinanceCategory.objects.create(
            organization_id=authorization.organization_id,
            kind=kind,
            name=clean_name,
            normalized_name=clean_name.casefold(),
            created_by_membership_id=authorization.membership_id,
        )
        _complete_command(
            authorization,
            command_type="create_category",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="category",
            result_reference=row.pk,
        )
        return row


def create_period(
    actor: User,
    organization_reference: UUID | str,
    *,
    starts_on: date,
    ends_on: date,
    label: str,
    idempotency_key: UUID,
) -> OperationalPeriod:
    payload = {"starts_on": starts_on, "ends_on": ends_on, "label": label}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_CLOSE_PERIOD
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_period",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return _period(authorization, replay[1])
        expected_end = (
            date(starts_on.year + 1, 1, 1)
            if starts_on.month == 12
            else date(starts_on.year, starts_on.month + 1, 1)
        )
        if starts_on.day != 1 or ends_on != expected_end:
            raise invalid("El periodo debe cubrir un mes calendario completo.")
        _lock(f"finance:{authorization.organization_id}:periods")
        if OperationalPeriod.objects.filter(
            organization_id=authorization.organization_id,
            starts_on__lt=ends_on,
            ends_on__gt=starts_on,
        ).exists():
            raise conflict("period_overlap", "El periodo se solapa con otro periodo operativo.")
        organization = _organization(authorization)
        row = OperationalPeriod.objects.create(
            organization_id=authorization.organization_id,
            starts_on=starts_on,
            ends_on=ends_on,
            label=" ".join(label.split()) or calendar.month_name[starts_on.month],
            currency=organization.currency,
            created_by_membership_id=authorization.membership_id,
        )
        _complete_command(
            authorization,
            command_type="create_period",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="period",
            result_reference=row.pk,
        )
        return row


def publish_direct_cost_plan(
    actor: User,
    organization_reference: UUID | str,
    *,
    root_reservation_id: UUID | str,
    venue_id: UUID | str,
    currency_value: str,
    reason: str,
    lines: list[dict[str, object]],
    idempotency_key: UUID,
) -> DirectCostPlanRevision:
    root_id = _uuid(root_reservation_id, "La raíz de reserva")
    historical_venue_id = _uuid(venue_id, "La sede")
    payload = {
        "root_reservation_id": root_id,
        "venue_id": historical_venue_id,
        "currency": currency_value,
        "reason": reason,
        "lines": lines,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_PLAN_COSTS
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="publish_direct_cost_plan",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return DirectCostPlanRevision.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        execution = _execution(authorization, root_id, lock=True)
        if execution is None:
            raise unavailable("La preparación operativa")
        if execution.execution_started_at is not None:
            raise conflict(
                "cost_baseline_already_frozen",
                "La ejecución ya comenzó y la baseline planificada no puede sustituirse.",
            )
        _validate_root_venue(authorization, root_id, historical_venue_id)
        normalized_currency = _organization_currency(authorization, currency_value)
        if not lines:
            raise invalid("La revisión debe contener al menos una línea.")
        normalized_lines: list[tuple[FinanceCategory, str, Decimal]] = []
        for item in lines:
            category = _category(
                authorization,
                cast(UUID | str, item.get("category_id")),
                kinds=(FinanceCategory.Kind.DIRECT_COST,),
            )
            description = " ".join(str(item.get("description", "")).split())
            normalized_lines.append(
                (category, description or category.name, _positive(cast(Any, item.get("amount"))))
            )
        _lock(f"finance:{authorization.organization_id}:plan:{root_id}")
        revision = (
            DirectCostPlanRevision.objects.filter(
                organization_id=authorization.organization_id,
                root_reservation_id=root_id,
            ).aggregate(value=Max("revision"))["value"]
            or 0
        ) + 1
        now = timezone.now()
        row = DirectCostPlanRevision.objects.create(
            organization_id=authorization.organization_id,
            root_reservation_id=root_id,
            venue_id=historical_venue_id,
            revision=revision,
            currency=normalized_currency,
            reason=reason.strip(),
            published_by_membership_id=authorization.membership_id,
            published_at=now,
        )
        DirectCostPlanLine.objects.bulk_create(
            [
                DirectCostPlanLine(
                    organization_id=authorization.organization_id,
                    plan_revision=row,
                    category=category,
                    position=position,
                    description=description,
                    amount=line_amount,
                    currency=normalized_currency,
                )
                for position, (category, description, line_amount) in enumerate(
                    normalized_lines, start=1
                )
            ]
        )
        _complete_command(
            authorization,
            command_type="publish_direct_cost_plan",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="direct_cost_plan",
            result_reference=row.pk,
        )
        return row


def submit_cost_evidence(
    actor: User,
    organization_reference: UUID | str,
    *,
    root_reservation_id: UUID | str,
    venue_id: UUID | str,
    category_id: UUID | str,
    amount_value: Decimal | int | str,
    currency_value: str,
    economic_date: date,
    description: str,
    evidence_reference: str,
    idempotency_key: UUID,
) -> OperationalCostEvidence:
    root_id = _uuid(root_reservation_id, "La raíz de reserva")
    historical_venue_id = _uuid(venue_id, "La sede")
    payload = {
        "root_reservation_id": root_id,
        "venue_id": historical_venue_id,
        "category_id": category_id,
        "amount": amount_value,
        "currency": currency_value,
        "economic_date": economic_date,
        "description": description,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_SUBMIT_EVIDENCE
    ) as authorization:
        if organizations_port.requires_operation_manage_for_finance_evidence(authorization):
            authorization.require(Capability.OPERATION_MANAGE)
        replay = _command_replay(
            authorization,
            command_type="submit_cost_evidence",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return OperationalCostEvidence.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        if _execution(authorization, root_id) is None:
            raise unavailable("La preparación operativa")
        _validate_root_venue(authorization, root_id, historical_venue_id)
        category = _category(authorization, category_id, kinds=(FinanceCategory.Kind.DIRECT_COST,))
        row = OperationalCostEvidence.objects.create(
            organization_id=authorization.organization_id,
            root_reservation_id=root_id,
            venue_id=historical_venue_id,
            category=category,
            amount=_positive(amount_value),
            currency=_organization_currency(authorization, currency_value),
            economic_date=economic_date,
            description=description.strip(),
            evidence_reference=evidence_reference.strip(),
            submitted_by_membership_id=authorization.membership_id,
            submitted_at=timezone.now(),
        )
        _complete_command(
            authorization,
            command_type="submit_cost_evidence",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="cost_evidence",
            result_reference=row.pk,
        )
        return row


def _create_actual_cost(
    authorization: TenantAuthorization,
    *,
    root_id: UUID,
    venue_id: UUID,
    category: FinanceCategory,
    amount_value: Decimal,
    currency_value: str,
    economic_date: date,
    provenance: str,
    description: str,
    evidence_reference: str,
    source_evidence: OperationalCostEvidence | None,
) -> ActualDirectCost:
    return ActualDirectCost.objects.create(
        organization_id=authorization.organization_id,
        root_reservation_id=root_id,
        venue_id=venue_id,
        category=category,
        amount=amount_value,
        currency=currency_value,
        economic_date=economic_date,
        registration_period=_registration_period(authorization, economic_date),
        provenance=provenance,
        description=description.strip(),
        evidence_reference=evidence_reference.strip(),
        source_evidence=source_evidence,
        recorded_by_membership_id=authorization.membership_id,
        recorded_at=timezone.now(),
    )


def record_actual_direct_cost(
    actor: User,
    organization_reference: UUID | str,
    *,
    root_reservation_id: UUID | str,
    venue_id: UUID | str,
    category_id: UUID | str,
    amount_value: Decimal | int | str,
    currency_value: str,
    economic_date: date,
    description: str,
    evidence_reference: str,
    idempotency_key: UUID,
) -> ActualDirectCost:
    root_id = _uuid(root_reservation_id, "La raíz de reserva")
    historical_venue_id = _uuid(venue_id, "La sede")
    payload = {
        "root_reservation_id": root_id,
        "venue_id": historical_venue_id,
        "category_id": category_id,
        "amount": amount_value,
        "currency": currency_value,
        "economic_date": economic_date,
        "description": description,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_RECORD_ACTUALS
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="record_actual_direct_cost",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return ActualDirectCost.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        _validate_root_venue(authorization, root_id, historical_venue_id)
        row = _create_actual_cost(
            authorization,
            root_id=root_id,
            venue_id=historical_venue_id,
            category=_category(
                authorization, category_id, kinds=(FinanceCategory.Kind.DIRECT_COST,)
            ),
            amount_value=_positive(amount_value),
            currency_value=_organization_currency(authorization, currency_value),
            economic_date=economic_date,
            provenance=ActualDirectCost.Provenance.MANUAL,
            description=description,
            evidence_reference=evidence_reference,
            source_evidence=None,
        )
        _complete_command(
            authorization,
            command_type="record_actual_direct_cost",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="actual_direct_cost",
            result_reference=row.pk,
        )
        return row


def decide_cost_evidence(
    actor: User,
    organization_reference: UUID | str,
    *,
    evidence_id: UUID | str,
    decision: str,
    reason: str,
    idempotency_key: UUID,
) -> EvidenceDecision:
    evidence_uuid = _uuid(evidence_id, "La evidencia")
    payload = {"evidence_id": evidence_uuid, "decision": decision, "reason": reason}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_RECORD_ACTUALS
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="decide_cost_evidence",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return EvidenceDecision.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        try:
            _lock(f"finance:{authorization.organization_id}:evidence:{evidence_uuid}")
            evidence = OperationalCostEvidence.objects.get(
                organization_id=authorization.organization_id, pk=evidence_uuid
            )
        except OperationalCostEvidence.DoesNotExist:
            raise unavailable("La evidencia") from None
        if EvidenceDecision.objects.filter(
            organization_id=authorization.organization_id, evidence=evidence
        ).exists():
            raise conflict("evidence_already_decided", "La evidencia ya tiene una decisión.")
        if decision not in EvidenceDecision.Decision.values:
            raise invalid("La decisión no es válida.")
        now = timezone.now()
        row = EvidenceDecision.objects.create(
            organization_id=authorization.organization_id,
            evidence=evidence,
            decision=decision,
            reason=reason.strip(),
            decided_by_membership_id=authorization.membership_id,
            decided_at=now,
        )
        if decision == EvidenceDecision.Decision.APPROVED:
            _create_actual_cost(
                authorization,
                root_id=evidence.root_reservation_id,
                venue_id=evidence.venue_id,
                category=evidence.category,
                amount_value=evidence.amount,
                currency_value=evidence.currency,
                economic_date=evidence.economic_date,
                provenance=ActualDirectCost.Provenance.OPERATIONS_EVIDENCE,
                description=evidence.description,
                evidence_reference=evidence.evidence_reference,
                source_evidence=evidence,
            )
        _complete_command(
            authorization,
            command_type="decide_cost_evidence",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="evidence_decision",
            result_reference=row.pk,
        )
        return row


def _signed(direction: str, value: Decimal) -> Decimal:
    return value if direction == "increase" else -value


def _cost_effective(row: ActualDirectCost) -> Decimal:
    corrections = row.corrections.aggregate(
        increases=Sum("amount", filter=models_q(direction="increase")),
        decreases=Sum("amount", filter=models_q(direction="decrease")),
    )
    return row.amount + (corrections["increases"] or ZERO) - (corrections["decreases"] or ZERO)


def models_q(**kwargs: object) -> Any:
    from django.db.models import Q

    return Q(**kwargs)


def correct_direct_cost(
    actor: User,
    organization_reference: UUID | str,
    *,
    direct_cost_id: UUID | str,
    direction: str,
    amount_value: Decimal | int | str,
    economic_date: date,
    reason: str,
    evidence_reference: str,
    idempotency_key: UUID,
) -> DirectCostCorrection:
    target_id = _uuid(direct_cost_id, "El costo directo")
    payload = {
        "direct_cost_id": target_id,
        "direction": direction,
        "amount": amount_value,
        "economic_date": economic_date,
        "reason": reason,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_RECORD_ACTUALS
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="correct_direct_cost",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return DirectCostCorrection.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        try:
            _lock(f"finance:{authorization.organization_id}:cash:direct_cost:{target_id}")
            target = ActualDirectCost.objects.get(
                organization_id=authorization.organization_id, pk=target_id
            )
        except ActualDirectCost.DoesNotExist:
            raise unavailable("El costo directo") from None
        if direction not in DirectCostCorrection.Direction.values:
            raise invalid("La dirección no es válida.")
        normalized = _positive(amount_value)
        current_amount = _cost_effective(target)
        if direction == DirectCostCorrection.Direction.DECREASE:
            if normalized > current_amount:
                raise conflict("cost_below_zero", "La corrección dejaría el costo bajo cero.")
            if (
                _source_cash_net(
                    authorization.organization_id,
                    OperatingCashMovement.SourceKind.DIRECT_COST,
                    target.pk,
                )
                > current_amount - normalized
            ):
                raise conflict(
                    "cash_exceeds_source",
                    "La corrección dejaría la salida neta por encima del costo vigente.",
                )
        row = DirectCostCorrection.objects.create(
            organization_id=authorization.organization_id,
            direct_cost=target,
            direction=direction,
            amount=normalized,
            currency=target.currency,
            economic_date=economic_date,
            registration_period=_registration_period(authorization, economic_date),
            reason=reason.strip(),
            evidence_reference=evidence_reference.strip(),
            recorded_by_membership_id=authorization.membership_id,
            recorded_at=timezone.now(),
        )
        _complete_command(
            authorization,
            command_type="correct_direct_cost",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="direct_cost_correction",
            result_reference=row.pk,
        )
        return row


def create_recurring_rule(
    actor: User,
    organization_reference: UUID | str,
    *,
    category_id: UUID | str,
    name: str,
    amount_value: Decimal | int | str,
    currency_value: str,
    day_of_month: int,
    valid_from: date,
    valid_until: date | None,
    default_venue_id: UUID | str | None,
    idempotency_key: UUID,
) -> RecurringExpenseRule:
    venue_id = None if default_venue_id is None else _uuid(default_venue_id, "La sede")
    payload = {
        "category_id": category_id,
        "name": name,
        "amount": amount_value,
        "currency": currency_value,
        "day_of_month": day_of_month,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "default_venue_id": venue_id,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_MANAGE_RECURRING
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_recurring_rule",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return RecurringExpenseRule.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        if day_of_month < 1 or day_of_month > 28:
            raise invalid("El día de recurrencia debe estar entre 1 y 28.")
        if valid_until is not None and valid_until < valid_from:
            raise invalid("La vigencia de la regla no es válida.")
        if venue_id is not None:
            _validate_venue(authorization, venue_id)
        row = RecurringExpenseRule.objects.create(
            organization_id=authorization.organization_id,
            category=_category(
                authorization, category_id, kinds=(FinanceCategory.Kind.RECURRING_EXPENSE,)
            ),
            name=" ".join(name.split()),
            amount=_positive(amount_value),
            currency=_organization_currency(authorization, currency_value),
            day_of_month=day_of_month,
            valid_from=valid_from,
            valid_until=valid_until,
            default_venue_id=venue_id,
            created_by_membership_id=authorization.membership_id,
        )
        _complete_command(
            authorization,
            command_type="create_recurring_rule",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="recurring_rule",
            result_reference=row.pk,
        )
        return row


def _normalized_allocations(
    authorization: TenantAuthorization,
    allocations: list[dict[str, object]],
    *,
    expected_amount: Decimal,
) -> list[tuple[str, UUID | None, UUID | None, Decimal]]:
    if not allocations:
        raise invalid("El gasto requiere al menos una asignación.")
    result: list[tuple[str, UUID | None, UUID | None, Decimal]] = []
    for item in allocations:
        scope = str(item.get("scope", ""))
        root_id = (
            None
            if item.get("root_reservation_id") in {None, ""}
            else _uuid(cast(Any, item.get("root_reservation_id")), "La raíz de reserva")
        )
        venue_id = (
            None
            if item.get("venue_id") in {None, ""}
            else _uuid(cast(Any, item.get("venue_id")), "La sede")
        )
        if scope == ExpenseAllocation.Scope.BUSINESS:
            if root_id is not None or venue_id is not None:
                raise invalid("Una asignación de negocio no admite raíz ni sede.")
        elif scope == ExpenseAllocation.Scope.VENUE:
            if root_id is not None or venue_id is None:
                raise invalid("Una asignación de sede requiere solo venue_id.")
            _validate_venue(authorization, venue_id)
        elif scope == ExpenseAllocation.Scope.EVENT:
            if root_id is None or venue_id is None:
                raise invalid("Una asignación de evento requiere raíz y sede históricas.")
            _validate_root_venue(authorization, root_id, venue_id)
        else:
            raise invalid("El alcance de asignación no es válido.")
        result.append((scope, root_id, venue_id, _positive(cast(Any, item.get("amount")))))
    if sum((item[3] for item in result), ZERO) != expected_amount:
        raise invalid("Las asignaciones deben sumar exactamente el importe del gasto.")
    return result


def _normalized_cash_attributions(
    authorization: TenantAuthorization,
    source_kind: str,
    attributions: list[dict[str, object]],
    *,
    expected_amount: Decimal,
) -> list[NormalizedAttribution]:
    if source_kind == OperatingCashMovement.SourceKind.DIRECT_COST:
        if attributions:
            raise invalid("La caja de un costo directo no admite atribuciones de gasto.")
        return []
    if source_kind != OperatingCashMovement.SourceKind.EXPENSE:
        raise invalid("El tipo de origen de caja no es válido.")
    normalized = _normalized_allocations(
        authorization, attributions, expected_amount=expected_amount
    )
    keys = [(scope, root_id, venue_id) for scope, root_id, venue_id, _ in normalized]
    if len(keys) != len(set(keys)):
        raise invalid("Una atribución de caja no puede repetir el mismo alcance.")
    return normalized


def _attribution_json(attributions: list[NormalizedAttribution]) -> list[dict[str, object]]:
    return [
        {
            "scope": scope,
            "root_reservation_id": None if root_id is None else str(root_id),
            "venue_id": None if venue_id is None else str(venue_id),
            "amount": format(attributed, ".2f"),
        }
        for scope, root_id, venue_id, attributed in attributions
    ]


def _attribution_map(value: object) -> dict[AttributionKey, Decimal]:
    result: dict[AttributionKey, Decimal] = {}
    for raw in cast(list[dict[str, object]], value):
        root_value = raw.get("root_reservation_id")
        venue_value = raw.get("venue_id")
        key = (
            str(raw["scope"]),
            None if root_value is None else UUID(str(root_value)),
            None if venue_value is None else UUID(str(venue_value)),
        )
        result[key] = result.get(key, ZERO) + amount(cast(Any, raw["amount"]))
    return result


def _create_expense(
    authorization: TenantAuthorization,
    *,
    category: FinanceCategory,
    expense_type: str,
    provenance: str,
    recurring_rule: RecurringExpenseRule | None,
    amount_value: Decimal,
    currency_value: str,
    economic_date: date,
    description: str,
    evidence_reference: str,
    allocations: list[tuple[str, UUID | None, UUID | None, Decimal]],
) -> ExpenseOccurrence:
    now = timezone.now()
    row = ExpenseOccurrence.objects.create(
        organization_id=authorization.organization_id,
        category=category,
        expense_type=expense_type,
        provenance=provenance,
        recurring_rule=recurring_rule,
        amount=amount_value,
        currency=currency_value,
        economic_date=economic_date,
        registration_period=_registration_period(authorization, economic_date),
        description=description.strip(),
        evidence_reference=evidence_reference.strip(),
        recorded_by_membership_id=authorization.membership_id,
        recorded_at=now,
    )
    ExpenseAllocation.objects.bulk_create(
        [
            ExpenseAllocation(
                organization_id=authorization.organization_id,
                expense_occurrence=row,
                position=position,
                scope=scope,
                root_reservation_id=root_id,
                venue_id=venue_id,
                amount=allocated,
                currency=currency_value,
            )
            for position, (scope, root_id, venue_id, allocated) in enumerate(allocations, start=1)
        ]
    )
    return row


def record_expense(
    actor: User,
    organization_reference: UUID | str,
    *,
    category_id: UUID | str,
    expense_type: str,
    amount_value: Decimal | int | str,
    currency_value: str,
    economic_date: date,
    description: str,
    evidence_reference: str,
    allocations: list[dict[str, object]],
    idempotency_key: UUID,
) -> ExpenseOccurrence:
    payload = {
        "category_id": category_id,
        "expense_type": expense_type,
        "amount": amount_value,
        "currency": currency_value,
        "economic_date": economic_date,
        "description": description,
        "evidence_reference": evidence_reference,
        "allocations": allocations,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_ALLOCATE_EXPENSES
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="record_expense",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return ExpenseOccurrence.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        if expense_type not in ExpenseOccurrence.ExpenseType.values:
            raise invalid("El tipo de gasto no es válido.")
        expected_kind = (
            FinanceCategory.Kind.VARIABLE_EXPENSE
            if expense_type == ExpenseOccurrence.ExpenseType.VARIABLE
            else FinanceCategory.Kind.RECURRING_EXPENSE
        )
        normalized_amount = _positive(amount_value)
        normalized_allocations = _normalized_allocations(
            authorization, allocations, expected_amount=normalized_amount
        )
        row = _create_expense(
            authorization,
            category=_category(authorization, category_id, kinds=(expected_kind,)),
            expense_type=expense_type,
            provenance=ExpenseOccurrence.Provenance.MANUAL,
            recurring_rule=None,
            amount_value=normalized_amount,
            currency_value=_organization_currency(authorization, currency_value),
            economic_date=economic_date,
            description=description,
            evidence_reference=evidence_reference,
            allocations=normalized_allocations,
        )
        _complete_command(
            authorization,
            command_type="record_expense",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="expense",
            result_reference=row.pk,
        )
        return row


def materialize_recurring_expense(
    actor: User,
    organization_reference: UUID | str,
    *,
    rule_id: UUID | str,
    economic_date: date,
    evidence_reference: str,
    idempotency_key: UUID,
) -> ExpenseOccurrence:
    target_id = _uuid(rule_id, "La regla recurrente")
    payload = {
        "rule_id": target_id,
        "economic_date": economic_date,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_MANAGE_RECURRING
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="materialize_recurring_expense",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return ExpenseOccurrence.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        try:
            _lock(f"finance:{authorization.organization_id}:recurring:{target_id}")
            rule = RecurringExpenseRule.objects.get(
                organization_id=authorization.organization_id, pk=target_id
            )
        except RecurringExpenseRule.DoesNotExist:
            raise unavailable("La regla recurrente") from None
        if (
            economic_date.day != rule.day_of_month
            or economic_date < rule.valid_from
            or (rule.valid_until is not None and economic_date > rule.valid_until)
        ):
            raise conflict(
                "recurrence_date_invalid",
                "La fecha no corresponde a la vigencia y día de la regla recurrente.",
            )
        scope = (
            ExpenseAllocation.Scope.BUSINESS
            if rule.default_venue_id is None
            else ExpenseAllocation.Scope.VENUE
        )
        row = _create_expense(
            authorization,
            category=rule.category,
            expense_type=ExpenseOccurrence.ExpenseType.RECURRING,
            provenance=ExpenseOccurrence.Provenance.RECURRING,
            recurring_rule=rule,
            amount_value=rule.amount,
            currency_value=rule.currency,
            economic_date=economic_date,
            description=rule.name,
            evidence_reference=evidence_reference,
            allocations=[(scope, None, rule.default_venue_id, rule.amount)],
        )
        _complete_command(
            authorization,
            command_type="materialize_recurring_expense",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="expense",
            result_reference=row.pk,
        )
        return row


def _expense_effective(row: ExpenseOccurrence) -> Decimal:
    corrections = row.corrections.aggregate(
        increases=Sum("amount", filter=models_q(direction="increase")),
        decreases=Sum("amount", filter=models_q(direction="decrease")),
    )
    return row.amount + (corrections["increases"] or ZERO) - (corrections["decreases"] or ZERO)


def _expense_scope_capacities(row: ExpenseOccurrence) -> dict[AttributionKey, Decimal]:
    result: defaultdict[AttributionKey, Decimal] = defaultdict(lambda: ZERO)
    for allocation in row.allocations.all():
        result[(allocation.scope, allocation.root_reservation_id, allocation.venue_id)] += (
            allocation.amount
        )
    for correction in row.corrections.all():
        key = (correction.scope, correction.root_reservation_id, correction.venue_id)
        result[key] += _signed(correction.direction, correction.amount)
    return dict(result)


def _expense_scope_cash_net(
    organization_id: UUID, expense_id: UUID
) -> dict[AttributionKey, Decimal]:
    result: defaultdict[AttributionKey, Decimal] = defaultdict(lambda: ZERO)
    rows = OperatingCashMovement.objects.prefetch_related("corrections").filter(
        organization_id=organization_id,
        source_kind=OperatingCashMovement.SourceKind.EXPENSE,
        source_id=expense_id,
    )
    for movement in rows:
        sign = (
            Decimal("1.00")
            if movement.direction == OperatingCashMovement.Direction.OUTFLOW
            else Decimal("-1.00")
        )
        for key, attributed in _cash_effective_attributions(movement).items():
            result[key] += sign * attributed
    return dict(result)


def correct_expense(
    actor: User,
    organization_reference: UUID | str,
    *,
    expense_id: UUID | str,
    direction: str,
    amount_value: Decimal | int | str,
    economic_date: date,
    scope: str,
    root_reservation_id: UUID | str | None,
    venue_id: UUID | str | None,
    reason: str,
    evidence_reference: str,
    idempotency_key: UUID,
) -> ExpenseOccurrenceCorrection:
    target_id = _uuid(expense_id, "El gasto")
    allocation_payload: dict[str, object] = {
        "scope": scope,
        "root_reservation_id": root_reservation_id,
        "venue_id": venue_id,
        "amount": amount_value,
    }
    payload = {
        "expense_id": target_id,
        "direction": direction,
        "economic_date": economic_date,
        "allocation": allocation_payload,
        "reason": reason,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_ALLOCATE_EXPENSES
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="correct_expense",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return ExpenseOccurrenceCorrection.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        try:
            _lock(f"finance:{authorization.organization_id}:cash:expense:{target_id}")
            target = ExpenseOccurrence.objects.get(
                organization_id=authorization.organization_id, pk=target_id
            )
        except ExpenseOccurrence.DoesNotExist:
            raise unavailable("El gasto") from None
        if direction not in ExpenseOccurrenceCorrection.Direction.values:
            raise invalid("La dirección no es válida.")
        normalized = _positive(amount_value)
        normalized_allocation = _normalized_allocations(
            authorization, [allocation_payload], expected_amount=normalized
        )[0]
        current_amount = _expense_effective(target)
        if direction == ExpenseOccurrenceCorrection.Direction.DECREASE:
            if normalized > current_amount:
                raise conflict("expense_below_zero", "La corrección dejaría el gasto bajo cero.")
            if (
                _source_cash_net(
                    authorization.organization_id,
                    OperatingCashMovement.SourceKind.EXPENSE,
                    target.pk,
                )
                > current_amount - normalized
            ):
                raise conflict(
                    "cash_exceeds_source",
                    "La corrección dejaría la salida neta por encima del gasto vigente.",
                )
            scope_key = normalized_allocation[:3]
            scope_capacity = _expense_scope_capacities(target).get(scope_key, ZERO)
            scope_cash = _expense_scope_cash_net(authorization.organization_id, target.pk).get(
                scope_key, ZERO
            )
            if scope_capacity - normalized < scope_cash:
                raise conflict(
                    "cash_exceeds_allocation",
                    "La corrección dejaría la caja por encima de su asignación explícita.",
                )
        row = ExpenseOccurrenceCorrection.objects.create(
            organization_id=authorization.organization_id,
            expense_occurrence=target,
            direction=direction,
            amount=normalized,
            currency=target.currency,
            economic_date=economic_date,
            registration_period=_registration_period(authorization, economic_date),
            scope=normalized_allocation[0],
            root_reservation_id=normalized_allocation[1],
            venue_id=normalized_allocation[2],
            reason=reason.strip(),
            evidence_reference=evidence_reference.strip(),
            recorded_by_membership_id=authorization.membership_id,
            recorded_at=timezone.now(),
        )
        _complete_command(
            authorization,
            command_type="correct_expense",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="expense_correction",
            result_reference=row.pk,
        )
        return row


def publish_budget(
    actor: User,
    organization_reference: UUID | str,
    *,
    period_id: UUID | str,
    venue_id: UUID | str | None,
    currency_value: str,
    reason: str,
    lines: list[dict[str, object]],
    idempotency_key: UUID,
) -> OperatingBudgetRevision:
    historical_venue_id = None if venue_id is None else _uuid(venue_id, "La sede")
    payload = {
        "period_id": period_id,
        "venue_id": historical_venue_id,
        "currency": currency_value,
        "reason": reason,
        "lines": lines,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_MANAGE_BUDGETS
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="publish_budget",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return OperatingBudgetRevision.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        period = _period(authorization, period_id, lock=True)
        if _is_closed(period):
            raise conflict("period_closed", "El periodo está cerrado.")
        if historical_venue_id is not None:
            _validate_venue(authorization, historical_venue_id)
        if not lines:
            raise invalid("El presupuesto requiere al menos una línea.")
        normalized_currency = _organization_currency(authorization, currency_value)
        normalized_lines = [
            (
                _category(authorization, cast(Any, item.get("category_id"))),
                _positive(cast(Any, item.get("amount"))),
            )
            for item in lines
        ]
        _lock(f"finance:{authorization.organization_id}:budget:{period.pk}:{historical_venue_id}")
        revision = (
            OperatingBudgetRevision.objects.filter(
                organization_id=authorization.organization_id,
                period=period,
                venue_id=historical_venue_id,
            ).aggregate(value=Max("revision"))["value"]
            or 0
        ) + 1
        row = OperatingBudgetRevision.objects.create(
            organization_id=authorization.organization_id,
            period=period,
            venue_id=historical_venue_id,
            revision=revision,
            currency=normalized_currency,
            reason=reason.strip(),
            published_by_membership_id=authorization.membership_id,
            published_at=timezone.now(),
        )
        OperatingBudgetLine.objects.bulk_create(
            [
                OperatingBudgetLine(
                    organization_id=authorization.organization_id,
                    budget_revision=row,
                    category=category,
                    position=position,
                    amount=line_amount,
                    currency=normalized_currency,
                )
                for position, (category, line_amount) in enumerate(normalized_lines, start=1)
            ]
        )
        _complete_command(
            authorization,
            command_type="publish_budget",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="budget",
            result_reference=row.pk,
        )
        return row


def _source_amount(
    authorization: TenantAuthorization, source_kind: str, source_id: UUID, *, lock: bool
) -> tuple[Decimal, str]:
    if source_kind == OperatingCashMovement.SourceKind.DIRECT_COST:
        if lock:
            _lock(f"finance:{authorization.organization_id}:cash:{source_kind}:{source_id}")
        try:
            source = ActualDirectCost.objects.get(
                organization_id=authorization.organization_id, pk=source_id
            )
        except ActualDirectCost.DoesNotExist:
            raise unavailable("El costo directo") from None
        return _cost_effective(source), source.currency
    if source_kind == OperatingCashMovement.SourceKind.EXPENSE:
        if lock:
            _lock(f"finance:{authorization.organization_id}:cash:{source_kind}:{source_id}")
        try:
            expense = ExpenseOccurrence.objects.get(
                organization_id=authorization.organization_id, pk=source_id
            )
        except ExpenseOccurrence.DoesNotExist:
            raise unavailable("El gasto") from None
        return _expense_effective(expense), expense.currency
    raise invalid("El origen de caja no es válido.")


def _cash_effective(row: OperatingCashMovement) -> Decimal:
    totals = row.corrections.aggregate(
        increases=Sum("amount", filter=models_q(direction="increase")),
        decreases=Sum("amount", filter=models_q(direction="decrease")),
    )
    return row.amount + (totals["increases"] or ZERO) - (totals["decreases"] or ZERO)


def _cash_effective_attributions(
    row: OperatingCashMovement,
) -> dict[AttributionKey, Decimal]:
    result = _attribution_map(row.expense_attributions)
    for correction in row.corrections.all():
        sign = Decimal("1.00") if correction.direction == "increase" else Decimal("-1.00")
        for key, attributed in _attribution_map(correction.expense_attributions).items():
            result[key] = result.get(key, ZERO) + sign * attributed
    return result


def _recovered_attributions(row: OperatingCashMovement) -> dict[AttributionKey, Decimal]:
    result: defaultdict[AttributionKey, Decimal] = defaultdict(lambda: ZERO)
    for recovery in row.recoveries.prefetch_related("corrections").all():
        for key, attributed in _cash_effective_attributions(recovery).items():
            result[key] += attributed
    return dict(result)


def _source_cash_net(organization_id: UUID, source_kind: str, source_id: UUID) -> Decimal:
    result = ZERO
    for row in OperatingCashMovement.objects.filter(
        organization_id=organization_id, source_kind=source_kind, source_id=source_id
    ):
        effective = _cash_effective(row)
        result += (
            effective if row.direction == OperatingCashMovement.Direction.OUTFLOW else -effective
        )
    return result


def record_cash_movement(
    actor: User,
    organization_reference: UUID | str,
    *,
    direction: str,
    source_kind: str,
    source_id: UUID | str,
    original_outflow_id: UUID | str | None,
    amount_value: Decimal | int | str,
    expense_attributions: list[dict[str, object]],
    economic_date: date,
    reason: str,
    evidence_reference: str,
    idempotency_key: UUID,
) -> OperatingCashMovement:
    source_uuid = _uuid(source_id, "El origen")
    outflow_uuid = (
        None if original_outflow_id is None else _uuid(original_outflow_id, "La salida original")
    )
    payload = {
        "direction": direction,
        "source_kind": source_kind,
        "source_id": source_uuid,
        "original_outflow_id": outflow_uuid,
        "amount": amount_value,
        "expense_attributions": expense_attributions,
        "economic_date": economic_date,
        "reason": reason,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_RECORD_CASH
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="record_cash_movement",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return OperatingCashMovement.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        if direction not in OperatingCashMovement.Direction.values:
            raise invalid("La dirección de caja no es válida.")
        normalized = _positive(amount_value)
        source_amount, source_currency = _source_amount(
            authorization, source_kind, source_uuid, lock=True
        )
        normalized_attributions = _normalized_cash_attributions(
            authorization,
            source_kind,
            expense_attributions,
            expected_amount=normalized,
        )
        attribution_values = _attribution_json(normalized_attributions)
        expense: ExpenseOccurrence | None = None
        if source_kind == OperatingCashMovement.SourceKind.EXPENSE:
            expense = (
                ExpenseOccurrence.objects.prefetch_related("allocations", "corrections")
                .filter(organization_id=authorization.organization_id, pk=source_uuid)
                .first()
            )
            if expense is None:
                raise unavailable("El gasto")
            capacities = _expense_scope_capacities(expense)
            if any(
                capacities.get((scope, root_id, venue_id), ZERO) <= ZERO
                for scope, root_id, venue_id, _ in normalized_attributions
            ):
                raise conflict(
                    "cash_allocation_not_available",
                    "La atribución de caja no corresponde a una asignación vigente del gasto.",
                )
        original: OperatingCashMovement | None = None
        if direction == OperatingCashMovement.Direction.OUTFLOW:
            if outflow_uuid is not None:
                raise invalid("Una salida no admite salida original.")
            if (
                _source_cash_net(authorization.organization_id, source_kind, source_uuid)
                + normalized
                > source_amount
            ):
                raise conflict(
                    "cash_exceeds_source",
                    "La salida neta excedería el costo o gasto vigente.",
                )
            if expense is not None:
                scope_cash = _expense_scope_cash_net(authorization.organization_id, expense.pk)
                for scope, root_id, venue_id, attributed in normalized_attributions:
                    key = (scope, root_id, venue_id)
                    if scope_cash.get(key, ZERO) + attributed > capacities[key]:
                        raise conflict(
                            "cash_exceeds_allocation",
                            "La salida excedería su asignación explícita de gasto.",
                        )
        else:
            if outflow_uuid is None:
                raise invalid("Una recuperación requiere la salida P11 original.")
            try:
                original = OperatingCashMovement.objects.prefetch_related(
                    "corrections", "recoveries__corrections"
                ).get(
                    organization_id=authorization.organization_id,
                    pk=outflow_uuid,
                    direction=OperatingCashMovement.Direction.OUTFLOW,
                    source_kind=source_kind,
                    source_id=source_uuid,
                )
            except OperatingCashMovement.DoesNotExist:
                raise unavailable("La salida original") from None
            recovered = sum((_cash_effective(row) for row in original.recoveries.all()), ZERO)
            if recovered + normalized > _cash_effective(original):
                raise conflict(
                    "recovery_exceeds_outflow",
                    "La recuperación excedería la salida P11 vigente.",
                )
            if expense is not None:
                original_attributions = _cash_effective_attributions(original)
                recovered_attributions = _recovered_attributions(original)
                for scope, root_id, venue_id, attributed in normalized_attributions:
                    key = (scope, root_id, venue_id)
                    if recovered_attributions.get(
                        key, ZERO
                    ) + attributed > original_attributions.get(key, ZERO):
                        raise conflict(
                            "recovery_exceeds_attribution",
                            "La recuperación excedería la atribución original de caja.",
                        )
        row = OperatingCashMovement.objects.create(
            organization_id=authorization.organization_id,
            direction=direction,
            source_kind=source_kind,
            source_id=source_uuid,
            original_outflow=original,
            amount=normalized,
            expense_attributions=attribution_values,
            currency=source_currency,
            economic_date=economic_date,
            registration_period=_registration_period(authorization, economic_date),
            reason=reason.strip(),
            evidence_reference=evidence_reference.strip(),
            recorded_by_membership_id=authorization.membership_id,
            recorded_at=timezone.now(),
        )
        _complete_command(
            authorization,
            command_type="record_cash_movement",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="cash_movement",
            result_reference=row.pk,
        )
        return row


def correct_cash_movement(
    actor: User,
    organization_reference: UUID | str,
    *,
    cash_movement_id: UUID | str,
    direction: str,
    amount_value: Decimal | int | str,
    expense_attributions: list[dict[str, object]],
    economic_date: date,
    reason: str,
    idempotency_key: UUID,
) -> CashMovementCorrection:
    target_id = _uuid(cash_movement_id, "El movimiento de caja")
    payload = {
        "cash_movement_id": target_id,
        "direction": direction,
        "amount": amount_value,
        "expense_attributions": expense_attributions,
        "economic_date": economic_date,
        "reason": reason,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_RECORD_CASH
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="correct_cash_movement",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return CashMovementCorrection.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        try:
            target_reference = OperatingCashMovement.objects.get(
                organization_id=authorization.organization_id, pk=target_id
            )
        except OperatingCashMovement.DoesNotExist:
            raise unavailable("El movimiento de caja") from None
        _source_amount(
            authorization,
            target_reference.source_kind,
            target_reference.source_id,
            lock=True,
        )
        target = OperatingCashMovement.objects.prefetch_related(
            "corrections", "recoveries__corrections"
        ).get(organization_id=authorization.organization_id, pk=target_reference.pk)
        if direction not in CashMovementCorrection.Direction.values:
            raise invalid("La dirección de corrección no es válida.")
        normalized = _positive(amount_value)
        normalized_attributions = _normalized_cash_attributions(
            authorization,
            target.source_kind,
            expense_attributions,
            expected_amount=normalized,
        )
        attribution_values = _attribution_json(normalized_attributions)
        effective = _cash_effective(target)
        if direction == CashMovementCorrection.Direction.DECREASE and normalized > effective:
            raise conflict("cash_below_zero", "La corrección dejaría el movimiento bajo cero.")
        corrected_effective = (
            effective + normalized
            if direction == CashMovementCorrection.Direction.INCREASE
            else effective - normalized
        )
        if target.direction == OperatingCashMovement.Direction.OUTFLOW:
            recovered = sum((_cash_effective(row) for row in target.recoveries.all()), ZERO)
            if recovered > corrected_effective:
                raise conflict(
                    "recovery_exceeds_outflow",
                    "La corrección dejaría la recuperación por encima de la salida.",
                )
        if target.source_kind == OperatingCashMovement.SourceKind.EXPENSE:
            base_attributions = _attribution_map(target.expense_attributions)
            current_attributions = _cash_effective_attributions(target)
            for scope, root_id, venue_id, attributed in normalized_attributions:
                key = (scope, root_id, venue_id)
                if key not in base_attributions:
                    raise conflict(
                        "cash_attribution_mismatch",
                        "La corrección debe conservar una atribución del movimiento original.",
                    )
                if (
                    direction == CashMovementCorrection.Direction.DECREASE
                    and attributed > current_attributions.get(key, ZERO)
                ):
                    raise conflict(
                        "cash_attribution_below_zero",
                        "La corrección dejaría una atribución de caja bajo cero.",
                    )
            if target.direction == OperatingCashMovement.Direction.OUTFLOW:
                recovered_attributions = _recovered_attributions(target)
                if direction == CashMovementCorrection.Direction.DECREASE:
                    for scope, root_id, venue_id, attributed in normalized_attributions:
                        key = (scope, root_id, venue_id)
                        if current_attributions.get(
                            key, ZERO
                        ) - attributed < recovered_attributions.get(key, ZERO):
                            raise conflict(
                                "recovery_exceeds_attribution",
                                "La corrección dejaría una recuperación sobre su atribución.",
                            )
                else:
                    expense = ExpenseOccurrence.objects.prefetch_related(
                        "allocations", "corrections"
                    ).get(
                        organization_id=authorization.organization_id,
                        pk=target.source_id,
                    )
                    capacities = _expense_scope_capacities(expense)
                    scope_cash = _expense_scope_cash_net(authorization.organization_id, expense.pk)
                    for scope, root_id, venue_id, attributed in normalized_attributions:
                        key = (scope, root_id, venue_id)
                        if scope_cash.get(key, ZERO) + attributed > capacities.get(key, ZERO):
                            raise conflict(
                                "cash_exceeds_allocation",
                                "La corrección excedería la asignación explícita del gasto.",
                            )
            elif direction == CashMovementCorrection.Direction.INCREASE:
                original = cast(OperatingCashMovement, target.original_outflow)
                original = OperatingCashMovement.objects.prefetch_related(
                    "corrections", "recoveries__corrections"
                ).get(pk=original.pk, organization_id=authorization.organization_id)
                original_attributions = _cash_effective_attributions(original)
                recovered_attributions = _recovered_attributions(original)
                for scope, root_id, venue_id, attributed in normalized_attributions:
                    key = (scope, root_id, venue_id)
                    if recovered_attributions.get(
                        key, ZERO
                    ) + attributed > original_attributions.get(key, ZERO):
                        raise conflict(
                            "recovery_exceeds_attribution",
                            "La corrección excedería la atribución original recuperable.",
                        )
        if direction == CashMovementCorrection.Direction.INCREASE:
            source_amount, _ = _source_amount(
                authorization, target.source_kind, target.source_id, lock=True
            )
            if target.direction == OperatingCashMovement.Direction.OUTFLOW:
                if (
                    _source_cash_net(
                        authorization.organization_id, target.source_kind, target.source_id
                    )
                    + normalized
                    > source_amount
                ):
                    raise conflict("cash_exceeds_source", "La salida excedería su origen.")
            else:
                original = cast(OperatingCashMovement, target.original_outflow)
                recovered = sum((_cash_effective(row) for row in original.recoveries.all()), ZERO)
                if recovered + normalized > _cash_effective(original):
                    raise conflict(
                        "recovery_exceeds_outflow", "La recuperación excedería la salida."
                    )
        row = CashMovementCorrection.objects.create(
            organization_id=authorization.organization_id,
            cash_movement=target,
            direction=direction,
            amount=normalized,
            expense_attributions=attribution_values,
            currency=target.currency,
            economic_date=economic_date,
            registration_period=_registration_period(authorization, economic_date),
            reason=reason.strip(),
            recorded_by_membership_id=authorization.membership_id,
            recorded_at=timezone.now(),
        )
        _complete_command(
            authorization,
            command_type="correct_cash_movement",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="cash_correction",
            result_reference=row.pk,
        )
        return row


def _recognition_adjustment_effective(row: RecognitionAdjustment) -> Decimal:
    totals = row.corrections.aggregate(
        increases=Sum("amount", filter=models_q(direction="increase")),
        decreases=Sum("amount", filter=models_q(direction="decrease")),
    )
    return row.amount + (totals["increases"] or ZERO) - (totals["decreases"] or ZERO)


def _recognition_net(organization_id: UUID, root_id: UUID) -> Decimal:
    result = ZERO
    for row in RecognitionAdjustment.objects.filter(
        organization_id=organization_id, root_reservation_id=root_id
    ):
        result += _signed(row.direction, _recognition_adjustment_effective(row))
    return result


def _completion_venue(
    authorization: TenantAuthorization, execution: operations_port.ExecutionEvidenceProjection
) -> UUID:
    history = _history(authorization, execution.root_reservation_id)
    for row in history.reservations:
        if row.reservation_id == execution.reservation_id:
            return row.venue_id
    raise conflict("execution_schedule_mismatch", "La ejecución no coincide con la agenda.")


def record_recognition_adjustment(
    actor: User,
    organization_reference: UUID | str,
    *,
    root_reservation_id: UUID | str,
    direction: str,
    amount_value: Decimal | int | str,
    currency_value: str,
    economic_date: date,
    reason_code: str,
    reason: str,
    evidence_reference: str,
    idempotency_key: UUID,
) -> RecognitionAdjustment:
    root_id = _uuid(root_reservation_id, "La raíz de reserva")
    payload = {
        "root_reservation_id": root_id,
        "direction": direction,
        "amount": amount_value,
        "currency": currency_value,
        "economic_date": economic_date,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_reference": evidence_reference,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_ADJUST_RECOGNITION
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="record_recognition_adjustment",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return RecognitionAdjustment.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        execution = _execution(authorization, root_id)
        if execution is None or execution.execution_completed_at is None:
            raise conflict(
                "execution_not_completed",
                "El ingreso solo puede ajustarse tras completar ejecución.",
            )
        completion_date = execution.execution_completed_at.astimezone(
            ZoneInfo(_organization(authorization).timezone_name)
        ).date()
        if economic_date < completion_date:
            raise invalid(
                "La fecha económica del ajuste no puede preceder la ejecución completada."
            )
        if direction not in RecognitionAdjustment.Direction.values:
            raise invalid("La dirección no es válida.")
        if reason_code not in RecognitionAdjustment.ReasonCode.values:
            raise conflict(
                "cancellation_consequence_not_authorized",
                "La razón no pertenece al catálogo cerrado de reconocimiento P11.",
            )
        normalized_reason = reason.casefold()
        if any(term in normalized_reason for term in FORBIDDEN_RECOGNITION_TERMS):
            raise conflict(
                "cancellation_consequence_not_authorized",
                "P11 no puede implementar consecuencias económicas de cancelación o anticipos.",
            )
        normalized = _positive(amount_value)
        _lock(f"finance:{authorization.organization_id}:recognition:{root_id}")
        sale = _sale(authorization, root_id)
        normalized_currency = _organization_currency(authorization, currency_value)
        if normalized_currency != sale.currency:
            raise invalid("La moneda no coincide con la venta confirmada.")
        if (
            direction == RecognitionAdjustment.Direction.DECREASE
            and sale.total + _recognition_net(authorization.organization_id, root_id) - normalized
            < ZERO
        ):
            raise conflict("recognized_revenue_below_zero", "El ingreso quedaría bajo cero.")
        row = RecognitionAdjustment.objects.create(
            organization_id=authorization.organization_id,
            root_reservation_id=root_id,
            venue_id=_completion_venue(authorization, execution),
            direction=direction,
            amount=normalized,
            currency=normalized_currency,
            economic_date=economic_date,
            registration_period=_registration_period(authorization, economic_date),
            reason_code=reason_code,
            reason=reason.strip(),
            evidence_reference=evidence_reference.strip(),
            recorded_by_membership_id=authorization.membership_id,
            recorded_at=timezone.now(),
        )
        _complete_command(
            authorization,
            command_type="record_recognition_adjustment",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="recognition_adjustment",
            result_reference=row.pk,
        )
        return row


def correct_recognition_adjustment(
    actor: User,
    organization_reference: UUID | str,
    *,
    recognition_adjustment_id: UUID | str,
    direction: str,
    amount_value: Decimal | int | str,
    economic_date: date,
    reason: str,
    idempotency_key: UUID,
) -> RecognitionAdjustmentCorrection:
    target_id = _uuid(recognition_adjustment_id, "El ajuste de reconocimiento")
    payload = {
        "recognition_adjustment_id": target_id,
        "direction": direction,
        "amount": amount_value,
        "economic_date": economic_date,
        "reason": reason,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_ADJUST_RECOGNITION
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="correct_recognition_adjustment",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return RecognitionAdjustmentCorrection.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        try:
            target_reference = RecognitionAdjustment.objects.get(
                organization_id=authorization.organization_id, pk=target_id
            )
        except RecognitionAdjustment.DoesNotExist:
            raise unavailable("El ajuste de reconocimiento") from None
        _lock(
            "finance:"
            f"{authorization.organization_id}:recognition:{target_reference.root_reservation_id}"
        )
        target = RecognitionAdjustment.objects.get(
            organization_id=authorization.organization_id,
            pk=target_reference.pk,
        )
        if direction not in RecognitionAdjustmentCorrection.Direction.values:
            raise invalid("La dirección no es válida.")
        normalized = _positive(amount_value)
        effective = _recognition_adjustment_effective(target)
        if (
            direction == RecognitionAdjustmentCorrection.Direction.DECREASE
            and normalized > effective
        ):
            raise conflict("recognition_adjustment_below_zero", "El ajuste quedaría bajo cero.")
        row = RecognitionAdjustmentCorrection.objects.create(
            organization_id=authorization.organization_id,
            recognition_adjustment=target,
            direction=direction,
            amount=normalized,
            currency=target.currency,
            economic_date=economic_date,
            registration_period=_registration_period(authorization, economic_date),
            reason=reason.strip(),
            recorded_by_membership_id=authorization.membership_id,
            recorded_at=timezone.now(),
        )
        if (
            _sale(authorization, target.root_reservation_id).total
            + _recognition_net(authorization.organization_id, target.root_reservation_id)
            < ZERO
        ):
            raise conflict("recognized_revenue_below_zero", "El ingreso quedaría bajo cero.")
        _complete_command(
            authorization,
            command_type="correct_recognition_adjustment",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="recognition_correction",
            result_reference=row.pk,
        )
        return row


def _period_data(row: OperationalPeriod) -> dict[str, object]:
    close = getattr(row, "close_snapshot", None)
    return {
        "id": row.pk,
        "label": row.label,
        "starts_on": row.starts_on,
        "ends_on": row.ends_on,
        "currency": row.currency,
        "closed": close is not None,
        "closed_at": None if close is None else close.closed_at,
    }


def _category_data(row: FinanceCategory) -> dict[str, object]:
    return {"id": row.pk, "kind": row.kind, "name": row.name}


def _metric_bucket() -> dict[str, Decimal]:
    return {
        "recognized_revenue": ZERO,
        "direct_cost": ZERO,
        "variable_expense": ZERO,
        "recurring_expense": ZERO,
        "p10_cash": ZERO,
        "p11_cash": ZERO,
    }


def _metric_result(bucket: dict[str, Decimal]) -> dict[str, object]:
    gross = bucket["recognized_revenue"] - bucket["direct_cost"]
    contribution = gross - bucket["variable_expense"]
    operating = contribution - bucket["recurring_expense"]
    return {
        **bucket,
        "gross_margin": gross,
        "contribution_margin": contribution,
        "operating_result": operating,
        "profitability_percentage": (
            None
            if bucket["recognized_revenue"] <= ZERO
            else amount(operating / bucket["recognized_revenue"] * HUNDRED)
        ),
        "net_cash_flow": bucket["p10_cash"] + bucket["p11_cash"],
    }


def _fact_in_filter(
    *,
    root_id: UUID | None,
    venue_id: UUID | None,
    root_filter: UUID | None,
    venue_filter: UUID | None,
) -> bool:
    return (root_filter is None or root_id == root_filter) and (
        venue_filter is None or venue_id == venue_filter
    )


def _is_prior(period: OperationalPeriod, economic_date: date) -> bool:
    return not (period.starts_on <= economic_date < period.ends_on)


def _classify_p10(
    source: receivables_port.FinanceCashContributionProjection,
    periods: tuple[OperationalPeriod, ...],
    timezone_name: str,
) -> tuple[OperationalPeriod, bool] | None:
    economic_date = source.economic_at.astimezone(ZoneInfo(timezone_name)).date()
    economic = next((row for row in periods if row.starts_on <= economic_date < row.ends_on), None)
    if economic is None:
        return None
    close = getattr(economic, "close_snapshot", None)
    if close is None or _p10_source_in_close(source, close):
        return economic, False
    for candidate in periods:
        if candidate.starts_on < economic.ends_on:
            continue
        candidate_close = getattr(candidate, "close_snapshot", None)
        if candidate_close is None or _p10_source_in_close(source, candidate_close):
            return candidate, True
    return None


def _p10_source_in_close(
    source: receivables_port.FinanceCashContributionProjection,
    close: PeriodCloseSnapshot,
) -> bool:
    references = cast(
        list[dict[str, object]],
        cast(dict[str, object], close.snapshot).get("p10_source_references", []),
    )
    return any(
        str(reference.get("source_kind")) == source.source_kind
        and str(reference.get("source_id")) == str(source.source_id)
        for reference in references
    )


def _overview_authorized(
    authorization: TenantAuthorization,
    *,
    period_id: UUID | None = None,
    root_filter: UUID | None = None,
    venue_filter: UUID | None = None,
    receivables_cutoff: datetime | None = None,
) -> dict[str, object]:
    organization = _organization(authorization)
    periods = tuple(
        OperationalPeriod.objects.select_related("close_snapshot")
        .filter(organization_id=authorization.organization_id)
        .order_by("starts_on", "id")
    )
    selected = (
        None if period_id is None else next((row for row in periods if row.pk == period_id), None)
    )
    if period_id is not None and selected is None:
        raise unavailable("El periodo")
    ordinary = _metric_bucket()
    prior = _metric_bucket()
    event_buckets: defaultdict[UUID, dict[str, Decimal]] = defaultdict(_metric_bucket)
    event_meta: dict[UUID, dict[str, object]] = {}

    executions = operations_port.execution_evidences_for_finance(authorization)
    execution_by_root = {row.root_reservation_id: row for row in executions}
    for execution in executions:
        root_id = execution.root_reservation_id
        if root_filter is not None and root_id != root_filter:
            continue
        completion_venue = _completion_venue(authorization, execution)
        event_meta[root_id] = {
            "root_reservation_id": root_id,
            "completed_reservation_id": (
                execution.reservation_id if execution.execution_completed_at is not None else None
            ),
            "recognized_venue_id": (
                completion_venue if execution.execution_completed_at is not None else None
            ),
            "execution_started_at": execution.execution_started_at,
            "execution_completed_at": execution.execution_completed_at,
        }
        if execution.execution_completed_at is None:
            continue
        completed_date = execution.execution_completed_at.astimezone(
            ZoneInfo(organization.timezone_name)
        ).date()
        if selected is not None and not (selected.starts_on <= completed_date < selected.ends_on):
            continue
        if venue_filter is not None and completion_venue != venue_filter:
            continue
        sale = _sale(authorization, root_id)
        ordinary["recognized_revenue"] += sale.total
        event_buckets[root_id]["recognized_revenue"] += sale.total

    plans = tuple(
        DirectCostPlanRevision.objects.prefetch_related("lines")
        .filter(organization_id=authorization.organization_id)
        .order_by("root_reservation_id", "revision")
    )
    plan_by_root: defaultdict[UUID, list[DirectCostPlanRevision]] = defaultdict(list)
    for plan in plans:
        plan_by_root[plan.root_reservation_id].append(plan)

    costs = tuple(
        ActualDirectCost.objects.select_related("category", "registration_period")
        .prefetch_related("corrections")
        .filter(organization_id=authorization.organization_id)
        .order_by("economic_date", "id")
    )
    for cost in costs:
        if not _fact_in_filter(
            root_id=cost.root_reservation_id,
            venue_id=cost.venue_id,
            root_filter=root_filter,
            venue_filter=venue_filter,
        ):
            continue
        if selected is None:
            event_buckets[cost.root_reservation_id]["direct_cost"] += _cost_effective(cost)
            ordinary["direct_cost"] += _cost_effective(cost)
        elif cost.registration_period_id == selected.pk:
            bucket = prior if _is_prior(selected, cost.economic_date) else ordinary
            bucket["direct_cost"] += cost.amount
            event_buckets[cost.root_reservation_id]["direct_cost"] += cost.amount
        if selected is not None:
            for correction in cost.corrections.all():
                if correction.registration_period_id != selected.pk:
                    continue
                effect = _signed(correction.direction, correction.amount)
                bucket = prior if _is_prior(selected, correction.economic_date) else ordinary
                bucket["direct_cost"] += effect
                event_buckets[cost.root_reservation_id]["direct_cost"] += effect

    expenses = tuple(
        ExpenseOccurrence.objects.select_related("category", "registration_period")
        .prefetch_related("allocations", "corrections")
        .filter(organization_id=authorization.organization_id)
        .order_by("economic_date", "id")
    )
    for expense in expenses:
        component = (
            "variable_expense"
            if expense.expense_type == ExpenseOccurrence.ExpenseType.VARIABLE
            else "recurring_expense"
        )
        include_original = selected is None or expense.registration_period_id == selected.pk
        for allocation in expense.allocations.all():
            if not include_original or not _fact_in_filter(
                root_id=allocation.root_reservation_id,
                venue_id=allocation.venue_id,
                root_filter=root_filter,
                venue_filter=venue_filter,
            ):
                continue
            target = (
                prior
                if selected is not None and _is_prior(selected, expense.economic_date)
                else ordinary
            )
            target[component] += allocation.amount
            if allocation.root_reservation_id is not None:
                event_buckets[allocation.root_reservation_id][component] += allocation.amount
        for expense_correction in expense.corrections.all():
            if selected is not None and expense_correction.registration_period_id != selected.pk:
                continue
            if not _fact_in_filter(
                root_id=expense_correction.root_reservation_id,
                venue_id=expense_correction.venue_id,
                root_filter=root_filter,
                venue_filter=venue_filter,
            ):
                continue
            effect = _signed(expense_correction.direction, expense_correction.amount)
            target = (
                prior
                if selected is not None and _is_prior(selected, expense_correction.economic_date)
                else ordinary
            )
            target[component] += effect
            if expense_correction.root_reservation_id is not None:
                event_buckets[expense_correction.root_reservation_id][component] += effect

    adjustments = tuple(
        RecognitionAdjustment.objects.select_related("registration_period")
        .prefetch_related("corrections")
        .filter(organization_id=authorization.organization_id)
    )
    for adjustment in adjustments:
        if not _fact_in_filter(
            root_id=adjustment.root_reservation_id,
            venue_id=adjustment.venue_id,
            root_filter=root_filter,
            venue_filter=venue_filter,
        ):
            continue
        if selected is None:
            effect = _signed(adjustment.direction, _recognition_adjustment_effective(adjustment))
            ordinary["recognized_revenue"] += effect
            event_buckets[adjustment.root_reservation_id]["recognized_revenue"] += effect
        elif adjustment.registration_period_id == selected.pk:
            effect = _signed(adjustment.direction, adjustment.amount)
            target = prior if _is_prior(selected, adjustment.economic_date) else ordinary
            target["recognized_revenue"] += effect
            event_buckets[adjustment.root_reservation_id]["recognized_revenue"] += effect
        if selected is not None:
            sign = Decimal("1.00") if adjustment.direction == "increase" else Decimal("-1.00")
            for recognition_correction in adjustment.corrections.all():
                if recognition_correction.registration_period_id != selected.pk:
                    continue
                effect = sign * _signed(
                    recognition_correction.direction, recognition_correction.amount
                )
                target = (
                    prior if _is_prior(selected, recognition_correction.economic_date) else ordinary
                )
                target["recognized_revenue"] += effect
                event_buckets[adjustment.root_reservation_id]["recognized_revenue"] += effect

    p10_sources = tuple(
        row
        for row in receivables_port.cash_contributions_for_finance(authorization)
        if receivables_cutoff is None or row.registered_at <= receivables_cutoff
    )
    included_p10: list[receivables_port.FinanceCashContributionProjection] = []
    for source in p10_sources:
        classification = _classify_p10(source, periods, organization.timezone_name)
        if classification is None:
            continue
        registration, is_prior = classification
        if selected is not None and registration.pk != selected.pk:
            continue
        if root_filter is not None and source.root_reservation_id != root_filter:
            continue
        if venue_filter is not None:
            if source.root_reservation_id is None:
                continue
            source_execution = execution_by_root.get(source.root_reservation_id)
            if (
                source_execution is None
                or _completion_venue(authorization, source_execution) != venue_filter
            ):
                continue
        effect = source.amount if source.direction == "inflow" else -source.amount
        (prior if is_prior else ordinary)["p10_cash"] += effect
        if source.root_reservation_id is not None:
            event_buckets[source.root_reservation_id]["p10_cash"] += effect
        included_p10.append(source)

    cash_rows = tuple(
        OperatingCashMovement.objects.select_related("registration_period")
        .prefetch_related("corrections")
        .filter(organization_id=authorization.organization_id)
    )
    cost_map = {row.pk: row for row in costs}

    def apply_cash_slice(
        *,
        root_id: UUID | None,
        venue_id: UUID | None,
        effect: Decimal,
        economic_date: date,
    ) -> None:
        if not _fact_in_filter(
            root_id=root_id,
            venue_id=venue_id,
            root_filter=root_filter,
            venue_filter=venue_filter,
        ):
            return
        target = prior if selected is not None and _is_prior(selected, economic_date) else ordinary
        target["p11_cash"] += effect
        if root_id is not None:
            event_buckets[root_id]["p11_cash"] += effect

    for cash in cash_rows:
        sign = Decimal("-1.00") if cash.direction == "outflow" else Decimal("1.00")
        if cash.source_kind == OperatingCashMovement.SourceKind.EXPENSE:
            if selected is None:
                for (
                    (_scope, attribution_root, attribution_venue),
                    attributed,
                ) in _cash_effective_attributions(cash).items():
                    apply_cash_slice(
                        root_id=attribution_root,
                        venue_id=attribution_venue,
                        effect=sign * attributed,
                        economic_date=cash.economic_date,
                    )
            else:
                if cash.registration_period_id == selected.pk:
                    for (
                        (_scope, attribution_root, attribution_venue),
                        attributed,
                    ) in _attribution_map(cash.expense_attributions).items():
                        apply_cash_slice(
                            root_id=attribution_root,
                            venue_id=attribution_venue,
                            effect=sign * attributed,
                            economic_date=cash.economic_date,
                        )
                for cash_correction in cash.corrections.all():
                    if cash_correction.registration_period_id != selected.pk:
                        continue
                    correction_sign = (
                        Decimal("1.00")
                        if cash_correction.direction == "increase"
                        else Decimal("-1.00")
                    )
                    for (
                        (_scope, attribution_root, attribution_venue),
                        attributed,
                    ) in _attribution_map(cash_correction.expense_attributions).items():
                        apply_cash_slice(
                            root_id=attribution_root,
                            venue_id=attribution_venue,
                            effect=sign * correction_sign * attributed,
                            economic_date=cash_correction.economic_date,
                        )
            continue

        if cash.source_kind == OperatingCashMovement.SourceKind.DIRECT_COST:
            source_cost = cost_map.get(cash.source_id)
            source_root = None if source_cost is None else source_cost.root_reservation_id
            source_venue = None if source_cost is None else source_cost.venue_id
        else:
            source_root = None
            source_venue = None
        if selected is None:
            apply_cash_slice(
                root_id=source_root,
                venue_id=source_venue,
                effect=sign * _cash_effective(cash),
                economic_date=cash.economic_date,
            )
        elif cash.registration_period_id == selected.pk:
            apply_cash_slice(
                root_id=source_root,
                venue_id=source_venue,
                effect=sign * cash.amount,
                economic_date=cash.economic_date,
            )
        if selected is not None:
            for cash_correction in cash.corrections.all():
                if cash_correction.registration_period_id != selected.pk:
                    continue
                apply_cash_slice(
                    root_id=source_root,
                    venue_id=source_venue,
                    effect=sign * _signed(cash_correction.direction, cash_correction.amount),
                    economic_date=cash_correction.economic_date,
                )

    presented = {key: ordinary[key] + prior[key] for key in ordinary}
    events: list[dict[str, object]] = []
    for root_id, bucket in sorted(event_buckets.items(), key=lambda item: str(item[0])):
        event_execution = execution_by_root.get(root_id)
        started_at = None if event_execution is None else event_execution.execution_started_at
        baseline = None
        if started_at is not None:
            revisions = plan_by_root[root_id]
            if revisions:
                baseline = revisions[-1]
        baseline_amount = (
            ZERO if baseline is None else sum((line.amount for line in baseline.lines.all()), ZERO)
        )
        events.append(
            {
                **event_meta.get(root_id, {"root_reservation_id": root_id}),
                "baseline_plan_revision_id": None if baseline is None else baseline.pk,
                "baseline_planned_cost": baseline_amount,
                "cost_variance": bucket["direct_cost"] - baseline_amount,
                "metrics": _metric_result(bucket),
            }
        )

    budgets = tuple(
        OperatingBudgetRevision.objects.select_related("period")
        .prefetch_related("lines__category")
        .filter(organization_id=authorization.organization_id)
        .order_by("period__starts_on", "venue_id", "revision", "id")
    )
    recurring_rules = tuple(
        RecurringExpenseRule.objects.select_related("category")
        .filter(organization_id=authorization.organization_id)
        .order_by("name", "id")
    )
    evidences = tuple(
        OperationalCostEvidence.objects.select_related("category", "decision")
        .filter(organization_id=authorization.organization_id)
        .order_by("economic_date", "id")
    )

    return {
        "organization_id": authorization.organization_id,
        "currency": organization.currency,
        "timezone": organization.timezone_name,
        "period": None if selected is None else _period_data(selected),
        "filters": {"root_reservation_id": root_filter, "venue_id": venue_filter},
        "ordinary": _metric_result(ordinary),
        "prior_period_adjustments": _metric_result(prior),
        "presented": _metric_result(presented),
        "events": events,
        "categories": [
            _category_data(row)
            for row in FinanceCategory.objects.filter(organization_id=authorization.organization_id)
        ],
        "periods": [_period_data(row) for row in periods],
        "direct_cost_plans": [
            {
                "id": row.pk,
                "root_reservation_id": row.root_reservation_id,
                "venue_id": row.venue_id,
                "revision": row.revision,
                "currency": row.currency,
                "reason": row.reason,
                "published_at": row.published_at,
                "lines": [
                    {
                        "id": line.pk,
                        "category_id": line.category_id,
                        "description": line.description,
                        "amount": line.amount,
                    }
                    for line in row.lines.all()
                ],
            }
            for row in plans
        ],
        "direct_costs": [
            {
                "id": row.pk,
                "root_reservation_id": row.root_reservation_id,
                "venue_id": row.venue_id,
                "category_id": row.category_id,
                "amount": row.amount,
                "effective_amount": _cost_effective(row),
                "currency": row.currency,
                "economic_date": row.economic_date,
                "registration_period_id": row.registration_period_id,
                "provenance": row.provenance,
                "description": row.description,
                "evidence_reference": row.evidence_reference,
            }
            for row in costs
        ],
        "cost_evidence": [
            {
                "id": row.pk,
                "root_reservation_id": row.root_reservation_id,
                "venue_id": row.venue_id,
                "category_id": row.category_id,
                "amount": row.amount,
                "currency": row.currency,
                "economic_date": row.economic_date,
                "description": row.description,
                "evidence_reference": row.evidence_reference,
                "decision": (
                    None
                    if not hasattr(row, "decision")
                    else {"id": row.decision.pk, "decision": row.decision.decision}
                ),
            }
            for row in evidences
        ],
        "expenses": [
            {
                "id": row.pk,
                "category_id": row.category_id,
                "expense_type": row.expense_type,
                "provenance": row.provenance,
                "amount": row.amount,
                "effective_amount": _expense_effective(row),
                "currency": row.currency,
                "economic_date": row.economic_date,
                "registration_period_id": row.registration_period_id,
                "description": row.description,
                "evidence_reference": row.evidence_reference,
                "allocations": [
                    {
                        "scope": allocation.scope,
                        "root_reservation_id": allocation.root_reservation_id,
                        "venue_id": allocation.venue_id,
                        "amount": allocation.amount,
                    }
                    for allocation in row.allocations.all()
                ],
            }
            for row in expenses
        ],
        "recurring_rules": [
            {
                "id": row.pk,
                "category_id": row.category_id,
                "name": row.name,
                "amount": row.amount,
                "currency": row.currency,
                "day_of_month": row.day_of_month,
                "valid_from": row.valid_from,
                "valid_until": row.valid_until,
                "default_venue_id": row.default_venue_id,
            }
            for row in recurring_rules
        ],
        "budgets": [
            {
                "id": row.pk,
                "period_id": row.period_id,
                "venue_id": row.venue_id,
                "revision": row.revision,
                "currency": row.currency,
                "reason": row.reason,
                "lines": [
                    {
                        "category_id": line.category_id,
                        "category_name": line.category.name,
                        "amount": line.amount,
                    }
                    for line in row.lines.all()
                ],
            }
            for row in budgets
        ],
        "cash_movements": [
            {
                "id": row.pk,
                "direction": row.direction,
                "source_kind": row.source_kind,
                "source_id": row.source_id,
                "original_outflow_id": row.original_outflow_id,
                "amount": row.amount,
                "effective_amount": _cash_effective(row),
                "expense_attributions": row.expense_attributions,
                "effective_expense_attributions": _attribution_json(
                    [
                        (*key, attributed)
                        for key, attributed in _cash_effective_attributions(row).items()
                    ]
                ),
                "corrections": [
                    {
                        "id": correction.pk,
                        "direction": correction.direction,
                        "amount": correction.amount,
                        "expense_attributions": correction.expense_attributions,
                        "economic_date": correction.economic_date,
                        "registration_period_id": correction.registration_period_id,
                    }
                    for correction in row.corrections.all()
                ],
                "currency": row.currency,
                "economic_date": row.economic_date,
                "registration_period_id": row.registration_period_id,
                "reason": row.reason,
                "evidence_reference": row.evidence_reference,
            }
            for row in cash_rows
        ],
        "recognition_adjustments": [
            {
                "id": row.pk,
                "root_reservation_id": row.root_reservation_id,
                "venue_id": row.venue_id,
                "direction": row.direction,
                "amount": row.amount,
                "effective_amount": _recognition_adjustment_effective(row),
                "currency": row.currency,
                "economic_date": row.economic_date,
                "registration_period_id": row.registration_period_id,
                "reason_code": row.reason_code,
                "reason": row.reason,
                "evidence_reference": row.evidence_reference,
            }
            for row in adjustments
        ],
        "p10_source_references": [
            {
                "source_kind": row.source_kind,
                "source_id": row.source_id,
                "registered_at": row.registered_at,
                "economic_at": row.economic_at,
            }
            for row in included_p10
        ],
    }


def finance_overview(
    actor: User,
    organization_reference: UUID | str,
    *,
    period_id: UUID | str | None = None,
    root_reservation_id: UUID | str | None = None,
    venue_id: UUID | str | None = None,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_READ
    ) as authorization:
        period_uuid = None if period_id is None else _uuid(period_id, "El periodo")
        root_uuid = (
            None
            if root_reservation_id is None
            else _uuid(root_reservation_id, "La raíz de reserva")
        )
        venue_uuid = None if venue_id is None else _uuid(venue_id, "La sede")
        if period_uuid is not None and root_uuid is None and venue_uuid is None:
            close = PeriodCloseSnapshot.objects.filter(
                organization_id=authorization.organization_id, period_id=period_uuid
            ).first()
            if close is not None:
                return cast(dict[str, object], close.snapshot)
        return _overview_authorized(
            authorization,
            period_id=period_uuid,
            root_filter=root_uuid,
            venue_filter=venue_uuid,
        )


def evidence_context(actor: User, organization_reference: UUID | str) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_SUBMIT_EVIDENCE
    ) as authorization:
        if organizations_port.requires_operation_manage_for_finance_evidence(authorization):
            authorization.require(Capability.OPERATION_MANAGE)
        events = []
        for execution in operations_port.execution_evidences_for_finance(authorization):
            history = _history(authorization, execution.root_reservation_id)
            events.append(
                {
                    "root_reservation_id": execution.root_reservation_id,
                    "reservation_id": execution.reservation_id,
                    "venues": sorted({row.venue_id for row in history.reservations}, key=str),
                }
            )
        return {
            "categories": [
                _category_data(row)
                for row in FinanceCategory.objects.filter(
                    organization_id=authorization.organization_id,
                    kind=FinanceCategory.Kind.DIRECT_COST,
                )
            ],
            "events": events,
        }


def close_period(
    actor: User,
    organization_reference: UUID | str,
    *,
    period_id: UUID | str,
    idempotency_key: UUID,
) -> PeriodCloseSnapshot:
    target_id = _uuid(period_id, "El periodo")
    payload = {"period_id": target_id}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_CLOSE_PERIOD
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="close_period",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return PeriodCloseSnapshot.objects.get(
                organization_id=authorization.organization_id, pk=replay[1]
            )
        period = _period(authorization, target_id, lock=True)
        if _is_closed(period):
            raise conflict("period_closed", "El periodo ya está cerrado.")
        if OperationalPeriod.objects.filter(
            organization_id=authorization.organization_id,
            starts_on__lt=period.starts_on,
            close_snapshot__isnull=True,
        ).exists():
            raise conflict(
                "earlier_period_open", "Los periodos deben cerrarse en orden cronológico."
            )
        if period.ends_on > _local_today(authorization):
            raise conflict("period_not_ended", "El periodo todavía no ha finalizado.")
        cutoff = timezone.now()
        snapshot = _overview_authorized(
            authorization, period_id=period.pk, receivables_cutoff=cutoff
        )
        references = cast(list[dict[str, object]], snapshot["p10_source_references"])
        source_sha = payload_hash(references)
        snapshot["close"] = {
            "closed_at": cutoff,
            "receivables_cutoff_registered_at": cutoff,
            "receivables_source_count": len(references),
            "receivables_source_sha256": source_sha,
            "formula_version": "finance-p11-v1",
        }
        stored_snapshot = cast(dict[str, object], json_value(snapshot))
        row = PeriodCloseSnapshot.objects.create(
            organization_id=authorization.organization_id,
            period=period,
            snapshot=stored_snapshot,
            snapshot_sha256=payload_hash(stored_snapshot),
            receivables_cutoff_registered_at=cutoff,
            receivables_source_count=len(references),
            receivables_source_sha256=source_sha,
            closed_by_membership_id=authorization.membership_id,
            closed_at=cutoff,
        )
        _complete_command(
            authorization,
            command_type="close_period",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="period_close",
            result_reference=row.pk,
        )
        return row


def export_rows(
    actor: User,
    organization_reference: UUID | str,
    *,
    period_id: UUID | str | None = None,
    root_reservation_id: UUID | str | None = None,
    venue_id: UUID | str | None = None,
) -> tuple[tuple[str, ...], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.FINANCE_EXPORT
    ) as authorization:
        period_uuid = None if period_id is None else _uuid(period_id, "El periodo")
        root_uuid = (
            None
            if root_reservation_id is None
            else _uuid(root_reservation_id, "La raíz de reserva")
        )
        venue_uuid = None if venue_id is None else _uuid(venue_id, "La sede")
        data = _overview_authorized(
            authorization,
            period_id=period_uuid,
            root_filter=root_uuid,
            venue_filter=venue_uuid,
        )
        rows: list[tuple[str, ...]] = [
            (
                "row_type",
                "root_reservation_id",
                "venue_id",
                "recognized_revenue",
                "direct_cost",
                "variable_expense",
                "recurring_expense",
                "operating_result",
                "net_cash_flow",
                "currency",
            )
        ]
        presented = cast(dict[str, object], data["presented"])
        rows.append(
            (
                "scope_total",
                "" if root_uuid is None else str(root_uuid),
                "" if venue_uuid is None else str(venue_uuid),
                format(cast(Decimal, presented["recognized_revenue"]), ".2f"),
                format(cast(Decimal, presented["direct_cost"]), ".2f"),
                format(cast(Decimal, presented["variable_expense"]), ".2f"),
                format(cast(Decimal, presented["recurring_expense"]), ".2f"),
                format(cast(Decimal, presented["operating_result"]), ".2f"),
                format(cast(Decimal, presented["net_cash_flow"]), ".2f"),
                str(data["currency"]),
            )
        )
        for event in cast(list[dict[str, object]], data["events"]):
            metrics = cast(dict[str, object], event["metrics"])
            rows.append(
                (
                    "event",
                    str(event["root_reservation_id"]),
                    str(event.get("recognized_venue_id") or ""),
                    format(cast(Decimal, metrics["recognized_revenue"]), ".2f"),
                    format(cast(Decimal, metrics["direct_cost"]), ".2f"),
                    format(cast(Decimal, metrics["variable_expense"]), ".2f"),
                    format(cast(Decimal, metrics["recurring_expense"]), ".2f"),
                    format(cast(Decimal, metrics["operating_result"]), ".2f"),
                    format(cast(Decimal, metrics["net_cash_flow"]), ".2f"),
                    str(data["currency"]),
                )
            )
        return tuple(rows)
