from psycopg.rows import dict_row


def insert_account(conn, name):
    # The database generates id and created_at; balance starts at 0.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "INSERT INTO accounts (name) VALUES (%s) "
            "RETURNING id, name, balance, created_at",
            (name,),
        )
        return cur.fetchone()


def lock_account(conn, account_id):
    # Holds the account's row lock until the database transaction ends, so
    # requests on one account are applied one at a time. False if it does not exist.
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM accounts WHERE id = %s FOR UPDATE", (account_id,))
        return cur.fetchone() is not None


def add_to_balance(conn, account_id, delta):
    # The guard and the write are one statement, so the row lock covers both.
    # Returns None when the balance would go negative.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET balance = balance + %s "
            "WHERE id = %s AND balance + %s >= 0 RETURNING balance",
            (delta, account_id, delta),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_balance(conn, account_id):
    # Returns None when no account has this id.
    with conn.cursor() as cur:
        cur.execute("SELECT balance FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
        return row[0] if row else None
