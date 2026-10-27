from uuid import uuid4

import psycopg.errors

from app.db import get_connection
from app.repositories import accounts as accounts_repository
from app.repositories import transactions as transactions_repository
from app.services.accounts import AccountNotFound
from app.services.transactions import (
    REFERENCE_UNIQUE,
    BalanceLimitExceeded,
    DuplicateReference,
    InsufficientBalance,
)


class SameAccount(Exception):
    pass


def insert_leg(conn, account_id, transaction_type, amount, description, reference_id, transfer_id):
    try:
        return transactions_repository.insert_transaction(
            conn, account_id, transaction_type, amount, description, reference_id, transfer_id
        )
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name != REFERENCE_UNIQUE:
            raise
        raise DuplicateReference()


def create_transfer(source_id, destination_id, amount, description, reference_id):
    if source_id == destination_id:
        raise SameAccount()
    transfer_id = uuid4()
    # Both legs and both balance updates are one database transaction: all or nothing.
    with get_connection() as conn:
        # Lock the accounts in one fixed order, so two opposite transfers cannot deadlock.
        for account_id in sorted((source_id, destination_id)):
            if not accounts_repository.lock_account(conn, account_id):
                raise AccountNotFound()
        debit = insert_leg(conn, source_id, "debit", amount, description, reference_id, transfer_id)
        credit = insert_leg(conn, destination_id, "credit", amount, description, reference_id, transfer_id)
        source_balance = accounts_repository.add_to_balance(conn, source_id, -amount)
        if source_balance is None:
            # Leaving the block with an exception rolls back both inserted rows.
            raise InsufficientBalance()
        try:
            destination_balance = accounts_repository.add_to_balance(conn, destination_id, amount)
        except psycopg.errors.NumericValueOutOfRange:
            raise BalanceLimitExceeded()
    return {
        "transfer_id": transfer_id,
        "debit": {**debit, "balance": source_balance},
        "credit": {**credit, "balance": destination_balance},
    }
