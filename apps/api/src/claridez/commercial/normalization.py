from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")


def canonical_text(value: str, *, field: str, max_length: int) -> str:
    canonical = " ".join(value.split())
    if not canonical or len(canonical) > max_length:
        raise ValueError(f"{field} no es válido.")
    return canonical


def canonical_optional_text(value: str | None, *, field: str, max_length: int) -> str:
    if value is None or not value.strip():
        return ""
    return canonical_text(value, field=field, max_length=max_length)


def canonical_phone(value: str) -> str:
    compact = re.sub(r"[\s().-]", "", value)
    if compact.startswith("00593"):
        compact = compact[2:]
    if compact.startswith("+593"):
        national = compact[4:]
    elif compact.startswith("593"):
        national = compact[3:]
    elif compact.startswith("0"):
        national = compact[1:]
    else:
        national = compact
    if not (re.fullmatch(r"9\d{8}", national) or re.fullmatch(r"[2-7]\d{7}", national)):
        raise ValueError("El teléfono ecuatoriano no es válido.")
    return f"+593{national}"


def canonical_email(value: str | None) -> str:
    return value.strip().lower() if value is not None else ""


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
