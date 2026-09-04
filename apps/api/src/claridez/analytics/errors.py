from __future__ import annotations


class AnalyticsError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(code: str, message: str) -> AnalyticsError:
    return AnalyticsError(code, message)


def unavailable(message: str) -> AnalyticsError:
    return AnalyticsError("resource_not_available", message, status=404)


def conflict(code: str, message: str) -> AnalyticsError:
    return AnalyticsError(code, message, status=409)
