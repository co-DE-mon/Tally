import uuid

import psycopg
import pytest


def insert_account(cur, account_id=None, name="Test account"):
    account_id = account_id or str(uuid.uuid4())
    cur.execute(
        "INSERT INTO accounts (id, name, balance) VALUES (%s, %s, 0)",
        (account_id, name),
    )
    return account_id


def insert_transaction(
    cur, account_id, reference_id, transaction_id=None, amount=10, description=""
):
    transaction_id = transaction_id or str(uuid.uuid4())
    cur.execute(
        "INSERT INTO transactions "
        "(id, account_id, type, amount, description, reference_id) "
        "VALUES (%s, %s, 'credit', %s, %s, %s)",
        (transaction_id, account_id, amount, description, reference_id),
    )
    return transaction_id


def test_transaction_with_zero_amount_is_rejected(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_transaction(cur, account_id, "ref-zero", amount=0)


TEXT_LIMITS = [("reference_id", 100), ("description", 255)]


@pytest.mark.parametrize("field,limit", TEXT_LIMITS)
def test_text_over_limit_is_rejected(conn, field, limit):
    values = {"reference_id": "ref-long", "description": ""}
    values[field] = "x" * (limit + 1)
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_transaction(cur, account_id, **values)


@pytest.mark.parametrize("field,limit", TEXT_LIMITS)
def test_text_at_limit_is_accepted(conn, field, limit):
    values = {"reference_id": "ref-long", "description": ""}
    values[field] = "x" * limit
    with conn.cursor() as cur:
        insert_transaction(cur, insert_account(cur), **values)


def test_account_name_over_100_characters_is_rejected(conn):
    with conn.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        insert_account(cur, name="a" * 101)


def test_account_name_of_100_characters_is_accepted(conn):
    with conn.cursor() as cur:
        insert_account(cur, name="a" * 100)


def test_same_reference_id_on_one_account_is_rejected(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        insert_transaction(cur, account_id, "ref-dup")
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            insert_transaction(cur, account_id, "ref-dup")


def test_same_reference_id_on_different_accounts_is_allowed(conn):
    with conn.cursor() as cur:
        first = insert_account(cur)
        second = insert_account(cur)
        insert_transaction(cur, first, "ref-shared")
        insert_transaction(cur, second, "ref-shared")
        cur.execute(
            "SELECT count(*) FROM transactions WHERE reference_id = %s",
            ("ref-shared",),
        )
        assert cur.fetchone()[0] == 2


def test_two_accounts_cannot_share_an_id(conn):
    shared_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        insert_account(cur, shared_id)
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            insert_account(cur, shared_id)


def test_two_transactions_cannot_share_an_id(conn):
    shared_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        insert_transaction(cur, account_id, "ref-one", shared_id)
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            insert_transaction(cur, account_id, "ref-two", shared_id)


def test_balance_cannot_be_updated_below_zero(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("UPDATE accounts SET balance = -0.01 WHERE id = %s", (account_id,))


def test_negative_amount_is_rejected(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_transaction(cur, account_id, "ref-negative", amount=-1)


def test_type_outside_credit_and_debit_is_rejected(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO transactions (account_id, type, amount, reference_id) "
                "VALUES (%s, 'refund', 1, 'ref-type')",
                (account_id,),
            )


def test_blank_account_name_is_rejected(conn):
    with conn.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        insert_account(cur, name="   ")


def test_transaction_for_an_unknown_account_is_rejected(conn):
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as caught:
            insert_transaction(cur, str(uuid.uuid4()), "ref-orphan")
        assert caught.value.diag.constraint_name == "transactions_account_id_fkey"


def test_amount_past_the_column_limit_is_rejected(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.NumericValueOutOfRange):
            insert_transaction(cur, account_id, "ref-big", amount=10**16)


def test_balance_past_the_column_limit_is_rejected(conn):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.NumericValueOutOfRange):
            cur.execute("UPDATE accounts SET balance = 10000000000000000 WHERE id = %s", (account_id,))


@pytest.mark.parametrize("reference_id", ["", "   "])
def test_blank_reference_id_is_rejected(conn, reference_id):
    with conn.cursor() as cur:
        account_id = insert_account(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_transaction(cur, account_id, reference_id)
