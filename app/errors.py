import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

# Every error response has one shape: {"error": {"code": ..., "message": ...}}.

HTTP_ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_docs(description):
    # An entry for FastAPI's `responses=`, so /docs shows the real error body.
    return {"model": ErrorResponse, "description": description}


class ApiError(Exception):
    def __init__(self, status_code, code, message):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code, code, message, headers=None):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def validation_message(exc):
    # "amount: Input should be greater than 0", one entry per invalid field.
    parts = []
    for item in exc.errors():
        # loc starts with where the value came from (body, query, path); list
        # positions (integers) are dropped.
        field = ".".join(str(p) for p in item["loc"][1:] if isinstance(p, str))
        parts.append(f"{field or item['loc'][0]}: {item['msg']}")
    return "; ".join(parts)


def register_error_handlers(app: FastAPI):
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return error_response(422, "VALIDATION_ERROR", validation_message(exc))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        code = HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        return error_response(exc.status_code, code, str(exc.detail), exc.headers)

    @app.exception_handler(psycopg.OperationalError)
    async def handle_database_busy(request: Request, exc: psycopg.OperationalError):
        # A lock or statement timeout, or a database that cannot be reached.
        return error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "The service is busy or temporarily unavailable; retry shortly",
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        # Nothing from the exception reaches the client; the server log has it.
        return error_response(500, "INTERNAL_ERROR", "Internal server error")


class JsonErrorCORSMiddleware(CORSMiddleware):
    # Starlette answers a rejected preflight (disallowed origin, method or headers) with a
    # plain-text 400. Same status and headers, but in the one error shape.
    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code != 400:
            return response
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
        return error_response(400, "CORS_REJECTED", response.body.decode(), headers=headers)
