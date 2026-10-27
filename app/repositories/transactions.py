from psycopg.rows import dict_row


def insert_transaction(
    conn, account_id, transaction_type, amount, description, reference_id, transfer_id=None
):
    # The database generates id and created_at. created_at is the clock time of the
    # insert, not now() (the start of the database transaction), so it is taken
    # after the account lock and follows the order balances were applied.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "INSERT INTO transactions "
            "(account_id, type, amount, description, reference_id, transfer_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp()) "
            "RETURNING id, account_id, type, amount, description, reference_id, "
            "transfer_id, created_at",
            (account_id, transaction_type, amount, description, reference_id, transfer_id),
        )
        return cur.fetchone()


# transaction_type None means no filter.
HISTORY_FILTER = "account_id = %s AND (%s::text IS NULL OR type = %s)"


def count_transactions(conn, account_id, transaction_type):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM transactions WHERE {HISTORY_FILTER}",
            (account_id, transaction_type, transaction_type),
        )
        return cur.fetchone()[0]


def list_transactions(conn, account_id, transaction_type, limit, offset):
    # Latest first; id breaks ties so page boundaries are stable.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, account_id, type, amount, description, reference_id, transfer_id, created_at "
            "FROM transactions "
            f"WHERE {HISTORY_FILTER} "
            "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
            (account_id, transaction_type, transaction_type, limit, offset),
        )
        return cur.fetchall()
