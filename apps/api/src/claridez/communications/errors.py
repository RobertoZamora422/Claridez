class CommunicationsError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str) -> CommunicationsError:
    return CommunicationsError("invalid_request", message)


def unavailable(resource: str) -> CommunicationsError:
    return CommunicationsError(
        "resource_not_available", f"{resource} no está disponible.", status=404
    )


def conflict(code: str, message: str) -> CommunicationsError:
    return CommunicationsError(code, message, status=409)
