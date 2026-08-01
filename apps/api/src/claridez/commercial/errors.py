from __future__ import annotations


class CommercialError(Exception):
    """Error funcional seguro para materializar en la API."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str = "La solicitud no es válida.") -> CommercialError:
    return CommercialError("invalid_request", message)


def conflict(code: str, message: str) -> CommercialError:
    return CommercialError(code, message, status=409)


def unavailable(resource: str) -> CommercialError:
    return CommercialError("resource_not_available", f"{resource} no está disponible.", status=404)
