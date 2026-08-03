from __future__ import annotations


class CrmError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str = "La solicitud no es válida.") -> CrmError:
    return CrmError("invalid_request", message)


def conflict(code: str, message: str) -> CrmError:
    return CrmError(code, message, status=409)


def unavailable(resource: str) -> CrmError:
    return CrmError("resource_not_available", f"{resource} no está disponible.", status=404)
