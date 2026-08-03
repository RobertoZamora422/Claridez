from __future__ import annotations


class PeopleError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str = "La solicitud no es válida.") -> PeopleError:
    return PeopleError("invalid_request", message)


def conflict(code: str, message: str) -> PeopleError:
    return PeopleError(code, message, status=409)


def unavailable(resource: str) -> PeopleError:
    return PeopleError("resource_not_available", f"{resource} no está disponible.", status=404)
