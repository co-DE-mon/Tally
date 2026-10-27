import re
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, field_validator

from app.errors import ApiError, error_docs
from app.services import transactions as transactions_service

router = APIRouter()

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
# Keeps (page - 1) * limit far below the database's bigint range, which gave a 500.
MAX_PAGE = 1_000_000
# A float keeps at most 15 significant digits exactly; more could be altered silently.
MAX_FLOAT_DIGITS = 15
PLAIN_DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")


class MoneyFields(BaseModel):
    # The fields and checks a transaction and a transfer have in common.
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    # Postgres text cannot hold NUL, so reject it here instead of failing with a 500.
    description: str = Field(default="", max_length=255, pattern=r"^[^\x00]*$")
    reference_id: str = Field(max_length=100, pattern=r"^[^\x00]*$")

    @field_validator("amount", mode="before")
    @classmethod
    def exact_amount(cls, value):
        # Only input that means exactly one decimal gets through: a plain decimal
        # string, an integer, or a float that cannot have lost digits.
        if isinstance(value, str) and PLAIN_DECIMAL.fullmatch(value):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float):
            text = repr(value)
            digits = text.replace("-", "").replace(".", "").lstrip("0")
            if "e" not in text and len(digits) <= MAX_FLOAT_DIGITS:
                return text
        raise ValueError(
            "amount must be a plain decimal such as 10.50; send it as a string if it has more than 15 digits"
        )

    @field_validator("reference_id")
    @classmethod
    def clean_reference_id(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("reference_id must not be blank")
        return value


class TransactionCreate(MoneyFields):
    type: Literal["credit", "debit"]


class TransactionItem(BaseModel):
    id: UUID
    account_id: UUID
    type: str
    amount: Decimal
    description: str
    reference_id: str
    transfer_id: UUID | None = None
    created_at: datetime


class TransactionResponse(TransactionItem):
    balance: Decimal


class HistoryResponse(BaseModel):
    data: list[TransactionItem]
    page: int
    limit: int
    total_records: int
    total_pages: int


@router.post(
    "/accounts/{account_id}/transactions",
    status_code=201,
    response_model=TransactionResponse,
    responses={
        404: error_docs("Account not found (ACCOUNT_NOT_FOUND)"),
        409: error_docs("Reference already used on this account (DUPLICATE_REFERENCE)"),
    },
)
def create_transaction(account_id: UUID, body: TransactionCreate):
    try:
        return transactions_service.create_transaction(
            account_id, body.type, body.amount, body.description, body.reference_id
        )
    except transactions_service.AccountNotFound:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Account not found")
    except transactions_service.InsufficientBalance:
        raise ApiError(422, "INSUFFICIENT_BALANCE", "Insufficient balance")
    except transactions_service.BalanceLimitExceeded:
        raise ApiError(422, "BALANCE_LIMIT_EXCEEDED", "Balance limit exceeded")
    except transactions_service.DuplicateReference:
        raise ApiError(
            409, "DUPLICATE_REFERENCE", "This reference_id is already used on this account"
        )


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=HistoryResponse,
    responses={404: error_docs("Account not found (ACCOUNT_NOT_FOUND)")},
)
def get_history(
    account_id: UUID,
    response: Response,
    type: Literal["credit", "debit"] | None = None,
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_LIMIT, ge=1),
):
    # A limit above the maximum is clamped, and the header tells the client.
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
        response.headers["X-Pagination-Warning"] = f"limit clamped to {MAX_LIMIT}"
    try:
        return transactions_service.get_history(account_id, type, page, limit)
    except transactions_service.AccountNotFound:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Account not found")
