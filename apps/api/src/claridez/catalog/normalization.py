from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def canonical_text(value: str | None, *, field: str, max_length: int) -> str:
    if value is None:
        raise ValueError(f"{field} es obligatorio.")
    canonical = " ".join(value.split())
    if not canonical or len(canonical) > max_length:
        raise ValueError(f"{field} no es válido.")
    return canonical


def canonical_optional_text(value: str | None, *, field: str, max_length: int) -> str:
    if value is None or not value.strip():
        return ""
    return canonical_text(value, field=field, max_length=max_length)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
