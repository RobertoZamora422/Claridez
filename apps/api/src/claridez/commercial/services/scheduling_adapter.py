"""Traduce el puerto público de scheduling al contrato de error comercial 5.1."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from claridez.scheduling.public import SchedulingError

from ..errors import CommercialError


def scheduling_call[Result](command: Callable[..., Result], *args: Any, **kwargs: Any) -> Result:
    try:
        return command(*args, **kwargs)
    except SchedulingError as error:
        code = "schedule_conflict" if error.code == "availability_conflict" else error.code
        raise CommercialError(code, error.message, status=error.status) from error
