import os

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import app


def pytest_configure(config):
    # Point the app and the tests at the test database, so a run can never touch
    # the main database (the app reads DB_NAME each time it connects).
    test_db = os.environ.get("TEST_DB_NAME")
    if not test_db:
        raise pytest.UsageError("TEST_DB_NAME is not set; load config/.env first.")
    if test_db == os.environ.get("DB_NAME"):
        # The client fixture deletes rows by name prefix, so never run on the main data.
        raise pytest.UsageError("TEST_DB_NAME must differ from DB_NAME.")
    os.environ["DB_NAME"] = test_db


@pytest.fixture(scope="session", autouse=True)
def only_the_test_database():
    # The client fixture deletes rows by name prefix, so check the database the app
    # really connects to, not just the environment variables.
    with get_connection() as connection:
        name = connection.execute("SELECT current_database()").fetchone()[0]
    if name != os.environ["TEST_DB_NAME"]:
        pytest.exit(f"App is connected to {name!r}, not the test database.", returncode=2)


@pytest.fixture
def client():
    # The API commits for real, so this fixture cleans up the accounts created
    # through it. Account names must start with "test-". Transactions go first
    # because they reference accounts.
    yield TestClient(app)
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM transactions WHERE account_id IN "
            "(SELECT id FROM accounts WHERE name LIKE 'test-%')"
        )
        connection.execute("DELETE FROM accounts WHERE name LIKE 'test-%'")


@pytest.fixture
def conn():
    connection = get_connection()
    yield connection
    # Undo everything the test wrote, so runs stay independent.
    connection.rollback()
    connection.close()
