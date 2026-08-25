from __future__ import annotations

import re
import unicodedata
from typing import Any


def canonical_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser texto.")
    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized:
        raise ValueError(f"{field} es obligatorio.")
    if len(normalized) > max_length:
        raise ValueError(f"{field} supera {max_length} caracteres.")
    return normalized


def canonical_optional_text(value: Any, *, field: str, max_length: int) -> str:
    if value in (None, ""):
        return ""
    return canonical_text(value, field=field, max_length=max_length)
