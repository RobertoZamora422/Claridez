class PortalError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str) -> PortalError:
    return PortalError("invalid_request", message)


def unavailable() -> PortalError:
    return PortalError("resource_not_available", "El recurso no está disponible.", status=404)


def forbidden() -> PortalError:
    return PortalError("forbidden", "La operación no está autorizada.", status=403)


def conflict(code: str, message: str) -> PortalError:
    return PortalError(code, message, status=409)
