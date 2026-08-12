from __future__ import annotations


class SchedulingError(Exception):
    """Error de dominio seguro del módulo de agenda."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(
    message: str = "La solicitud no es válida.", *, code: str = "invalid_request"
) -> SchedulingError:
    return SchedulingError(code, message)


def conflict(code: str, message: str) -> SchedulingError:
    return SchedulingError(code, message, status=409)


def unavailable(resource: str) -> SchedulingError:
    return SchedulingError("resource_not_available", f"{resource} no está disponible.", status=404)
