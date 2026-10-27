import os

import psycopg


# A request never waits longer than this for a row lock or runs a statement longer
# than this; it fails with a 503 instead of holding a worker thread.
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 10000


REQUIRED_SETTINGS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")


def check_settings():
    # Called at startup, so a missing setting stops the server with a clear message
    # instead of a 500 on the first request. Only names are shown, never values.
    missing = [name for name in REQUIRED_SETTINGS if name not in os.environ]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))


def get_connection():
    # Settings come from environment variables; DB_NAME selects the database.
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        connect_timeout=5,
        options=f"-c lock_timeout={LOCK_TIMEOUT_MS} -c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )
