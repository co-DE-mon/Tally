from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.errors import ApiError, error_docs
from app.services import accounts as accounts_service

router = APIRouter()


class AccountCreate(BaseModel):
    # Only name is read from the client; extra fields such as balance are ignored.
    # Postgres text cannot hold NUL, so reject it here instead of failing with a 500.
    name: str = Field(max_length=100, pattern=r"^[^\x00]*$")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class AccountResponse(BaseModel):
    id: UUID
    name: str
    balance: Decimal
    created_at: datetime


@router.post("/accounts", status_code=201, response_model=AccountResponse)
def create_account(body: AccountCreate):
    return accounts_service.create_account(body.name)


class BalanceResponse(BaseModel):
    account_id: UUID
    balance: Decimal


@router.get(
    "/accounts/{account_id}/balance",
    response_model=BalanceResponse,
    responses={404: error_docs("Account not found (ACCOUNT_NOT_FOUND)")},
)
def get_balance(account_id: UUID):
    try:
        return accounts_service.get_balance(account_id)
    except accounts_service.AccountNotFound:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Account not found")
