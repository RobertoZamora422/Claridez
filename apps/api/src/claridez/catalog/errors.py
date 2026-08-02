class CatalogError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str = "La solicitud no es válida.") -> CatalogError:
    return CatalogError("invalid_request", message)


def conflict(code: str, message: str) -> CatalogError:
    return CatalogError(code, message, status=409)


def unavailable(resource: str) -> CatalogError:
    return CatalogError("resource_not_available", f"{resource} no está disponible.", status=404)
