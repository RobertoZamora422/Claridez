from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

CENT = Decimal("0.01")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def amount(value: Decimal | int | str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError("Los importes deben enviarse como decimal, entero o texto.")
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(value)
        quantized = normalized.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("El importe no es válido.") from None
    if not quantized.is_finite():
        raise ValueError("El importe no es válido.")
    return quantized


def positive_amount(value: Decimal | int | str) -> Decimal:
    normalized = amount(value)
    if normalized <= Decimal("0.00"):
        raise ValueError("El importe debe ser mayor que cero.")
    return normalized


def currency(value: str) -> str:
    normalized = value.strip().upper()
    if not _CURRENCY.fullmatch(normalized):
        raise ValueError("La moneda debe ser un código ISO 4217 de tres letras.")
    return normalized


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def canonical_payload(value: Any) -> bytes:
    return json.dumps(
        _canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()
