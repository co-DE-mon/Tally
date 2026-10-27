from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.errors import ApiError, error_docs
from app.routes.transactions import MoneyFields, TransactionResponse
from app.services import transfers as transfers_service

router = APIRouter()


class TransferCreate(MoneyFields):
    source_account_id: UUID
    destination_account_id: UUID


class TransferResponse(BaseModel):
    transfer_id: UUID
    debit: TransactionResponse
    credit: TransactionResponse


@router.post(
    "/transfers",
    status_code=201,
    response_model=TransferResponse,
    responses={
        404: error_docs("Source or destination account not found (ACCOUNT_NOT_FOUND)"),
        409: error_docs("Reference already used on either account (DUPLICATE_REFERENCE)"),
    },
)
def create_transfer(body: TransferCreate):
    try:
        return transfers_service.create_transfer(
            body.source_account_id,
            body.destination_account_id,
            body.amount,
            body.description,
            body.reference_id,
        )
    except transfers_service.SameAccount:
        raise ApiError(422, "SAME_ACCOUNT", "Source and destination must be different accounts")
    except transfers_service.AccountNotFound:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Account not found")
    except transfers_service.InsufficientBalance:
        raise ApiError(422, "INSUFFICIENT_BALANCE", "Insufficient balance")
    except transfers_service.BalanceLimitExceeded:
        raise ApiError(422, "BALANCE_LIMIT_EXCEEDED", "Balance limit exceeded")
    except transfers_service.DuplicateReference:
        raise ApiError(
            409, "DUPLICATE_REFERENCE", "This reference_id is already used on this account"
        )
