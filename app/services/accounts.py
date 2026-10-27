from app.db import get_connection
from app.repositories import accounts as accounts_repository


class AccountNotFound(Exception):
    pass


def create_account(name):
    # The connection block commits on success, rolls back on error, then closes.
    with get_connection() as conn:
        return accounts_repository.insert_account(conn, name)


def get_balance(account_id):
    with get_connection() as conn:
        balance = accounts_repository.get_balance(conn, account_id)
    if balance is None:
        raise AccountNotFound()
    return {"account_id": account_id, "balance": balance}
