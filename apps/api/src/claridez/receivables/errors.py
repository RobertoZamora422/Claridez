from __future__ import annotations


class ReceivablesError(Exception):
    """Error funcional seguro de cuentas por cobrar."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str = "La solicitud financiera no es válida.") -> ReceivablesError:
    return ReceivablesError("invalid_request", message)


def conflict(code: str, message: str) -> ReceivablesError:
    return ReceivablesError(code, message, status=409)


def unavailable(resource: str = "El recurso financiero") -> ReceivablesError:
    return ReceivablesError("resource_not_available", f"{resource} no está disponible.", status=404)
