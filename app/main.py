from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import check_settings
from app.errors import JsonErrorCORSMiddleware, error_docs, register_error_handlers
from app.routes import accounts as accounts_routes
from app.routes import transactions as transactions_routes
from app.routes import transfers as transfers_routes

@asynccontextmanager
async def lifespan(app):
    check_settings()
    yield


app = FastAPI(
    lifespan=lifespan,
    responses={
        422: error_docs("Invalid input or a refused transaction (VALIDATION_ERROR, INSUFFICIENT_BALANCE, BALANCE_LIMIT_EXCEEDED)"),
        500: error_docs("Unexpected failure (INTERNAL_ERROR)"),
        503: error_docs("Database busy or unreachable; retry (SERVICE_UNAVAILABLE)"),
    }
)
register_error_handlers(app)
# Only the manual-testing page in frontend/ (python3 -m http.server 5500) may call the API from a browser.
app.add_middleware(
    JsonErrorCORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(accounts_routes.router)
app.include_router(transactions_routes.router)
app.include_router(transfers_routes.router)
