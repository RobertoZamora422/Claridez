from __future__ import annotations


class ResourcesError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str) -> ResourcesError:
    return ResourcesError("invalid_resources_command", message, status=400)


def conflict(code: str, message: str) -> ResourcesError:
    return ResourcesError(code, message, status=409)


def unavailable(label: str) -> ResourcesError:
    return ResourcesError("resource_not_available", f"{label} no está disponible.", status=404)
