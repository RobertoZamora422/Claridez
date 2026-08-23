from __future__ import annotations


class FinanceError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str) -> FinanceError:
    return FinanceError("invalid_finance_command", message, status=400)


def conflict(code: str, message: str) -> FinanceError:
    return FinanceError(code, message, status=409)


def unavailable(label: str) -> FinanceError:
    return FinanceError("resource_not_available", f"{label} no está disponible.", status=404)
