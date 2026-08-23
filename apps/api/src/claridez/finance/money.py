from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

CENT = Decimal("0.01")


def amount(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise ValueError("Los importes no admiten float.")
    try:
        normalized = Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("El importe no es válido.") from None
    if not normalized.is_finite():
        raise ValueError("El importe debe ser finito.")
    if normalized.copy_abs() >= Decimal("10000000000000000"):
        raise ValueError("El importe excede el límite permitido.")
    return normalized


def positive_amount(value: Decimal | int | str) -> Decimal:
    normalized = amount(value)
    if normalized <= 0:
        raise ValueError("El importe debe ser mayor que cero.")
    return normalized


def currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
        raise ValueError("La moneda debe ser un código ISO 4217 de tres letras.")
    return normalized


def json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, (UUID, date, datetime)):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def payload_hash(value: object) -> str:
    payload = json.dumps(
        json_value(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
