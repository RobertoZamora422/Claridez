from __future__ import annotations


class OperationsError(Exception):
    """Error de dominio seguro para la API operativa."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str = "La solicitud no es válida.") -> OperationsError:
    return OperationsError("invalid_request", message)


def conflict(code: str, message: str) -> OperationsError:
    return OperationsError(code, message, status=409)


def unavailable(resource: str = "El recurso") -> OperationsError:
    return OperationsError("resource_not_available", f"{resource} no está disponible.", status=404)
