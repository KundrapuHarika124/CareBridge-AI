"""Uniform API envelope and error types."""
from typing import Any

from fastapi import Request


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def bad_request(code: str, message: str, details: Any = None) -> AppError:
    return AppError(400, code, message, details)


def unauthorized(message: str = "Authentication required") -> AppError:
    return AppError(401, "UNAUTHENTICATED", message)


def forbidden(message: str = "You are not allowed to do this") -> AppError:
    return AppError(403, "FORBIDDEN", message)


def not_found(what: str = "Resource") -> AppError:
    # Also used for records outside the caller's scope, so IDs cannot be probed.
    return AppError(404, "NOT_FOUND", f"{what} not found")


def conflict(code: str, message: str, details: Any = None) -> AppError:
    return AppError(409, code, message, details)


def too_many_requests() -> AppError:
    return AppError(429, "RATE_LIMITED", "Too many requests. Please wait and try again.")


def unavailable(code: str, message: str) -> AppError:
    return AppError(503, code, message)


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def ok(request: Request, data: Any, **meta: Any) -> dict:
    return {"data": data, "meta": {"request_id": request_id_of(request), **meta}}


def error_body(request: Request, code: str, message: str, details: Any = None) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details},
        "meta": {"request_id": request_id_of(request)},
    }
