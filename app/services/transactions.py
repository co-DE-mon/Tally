import math

import psycopg.errors
from psycopg import IsolationLevel

from app.db import get_connection
from app.repositories import accounts as accounts_repository
from app.repositories import transactions as transactions_repository
from app.services.accounts import AccountNotFound


# Constraint names from db/schema.sql; the database decides, the service translates.
REFERENCE_UNIQUE = "transactions_account_id_reference_id_key"


class InsufficientBalance(Exception):
    pass


class DuplicateReference(Exception):
    pass


class BalanceLimitExceeded(Exception):
    pass


def create_transaction(account_id, transaction_type, amount, description, reference_id):
    # Lock, insert and balance update share one database transaction: both or neither.
    with get_connection() as conn:
        # Lock first: requests on one account queue here, so created_at (taken at
        # the insert) and the balance update happen in the same order.
        if not accounts_repository.lock_account(conn, account_id):
            raise AccountNotFound()
        try:
            transaction = transactions_repository.insert_transaction(
                conn, account_id, transaction_type, amount, description, reference_id
            )
        except psycopg.errors.UniqueViolation as exc:
            # Only the per-account reference rule is a duplicate; anything else is a bug.
            if exc.diag.constraint_name != REFERENCE_UNIQUE:
                raise
            raise DuplicateReference()
        delta = amount if transaction_type == "credit" else -amount
        try:
            balance = accounts_repository.add_to_balance(conn, account_id, delta)
        except psycopg.errors.NumericValueOutOfRange:
            # The new balance would not fit NUMERIC(18,2); the insert rolls back.
            raise BalanceLimitExceeded()
        if balance is None:
            # Leaving the block with an exception rolls back the inserted row.
            raise InsufficientBalance()
    return {**transaction, "balance": balance}


def get_history(account_id, transaction_type, page, limit):
    with get_connection() as conn:
        # One snapshot for the count and the rows, so total_records matches data.
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        total = transactions_repository.count_transactions(conn, account_id, transaction_type)
        # Any row proves the account exists, so only an empty result needs the check.
        if total == 0 and accounts_repository.get_balance(conn, account_id) is None:
            raise AccountNotFound()
        rows = transactions_repository.list_transactions(
            conn, account_id, transaction_type, limit, (page - 1) * limit
        )
    return {
        "data": rows,
        "page": page,
        "limit": limit,
        "total_records": total,
        "total_pages": math.ceil(total / limit),
    }
