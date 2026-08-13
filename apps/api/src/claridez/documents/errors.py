from __future__ import annotations


class DocumentsError(Exception):
    def __init__(self, code: str, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def conflict(code: str, detail: str) -> DocumentsError:
    return DocumentsError(code, detail, status_code=409)


def forbidden(detail: str = "La operación documental no está autorizada.") -> DocumentsError:
    return DocumentsError("forbidden", detail, status_code=403)


def unavailable(subject: str) -> DocumentsError:
    return DocumentsError("not_found", f"{subject} no está disponible.", status_code=404)
