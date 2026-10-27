import uuid
from datetime import datetime, timedelta, timezone

import pytest


def test_valid_name_returns_balance_zero(client):
    response = client.post("/accounts", json={"name": "test-valid"})
    assert response.status_code == 201
    assert response.json()["name"] == "test-valid"
    assert response.json()["balance"] == "0.00"


def test_missing_name_is_a_validation_error(client):
    response = client.post("/accounts", json={})
    assert response.status_code == 422
    assert "error" in response.json()


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_is_rejected(client, name):
    response = client.post("/accounts", json={"name": name})
    assert response.status_code == 422
    assert "error" in response.json()


def test_name_with_a_nul_character_is_rejected(client):
    response = client.post("/accounts", json={"name": "test-a\u0000b"})
    assert response.status_code == 422
    assert "error" in response.json()


def test_name_at_the_length_limit_is_accepted(client):
    response = client.post("/accounts", json={"name": "test-" + "a" * 95})
    assert response.status_code == 201


def test_name_over_the_length_limit_is_rejected(client):
    response = client.post("/accounts", json={"name": "test-" + "a" * 96})
    assert response.status_code == 422
    assert "error" in response.json()


def test_name_is_trimmed(client):
    response = client.post("/accounts", json={"name": "  test-trim  "})
    assert response.status_code == 201
    assert response.json()["name"] == "test-trim"


def test_client_supplied_balance_is_ignored(client):
    response = client.post("/accounts", json={"name": "test-balance", "balance": "500.00"})
    assert response.status_code == 201
    assert response.json()["balance"] == "0.00"


def test_client_supplied_id_and_created_at_are_ignored(client):
    sent_id = str(uuid.uuid4())
    response = client.post(
        "/accounts",
        json={"name": "test-ids", "id": sent_id, "created_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 201
    assert response.json()["id"] != sent_id
    created_at = datetime.fromisoformat(response.json()["created_at"])
    assert abs(datetime.now(timezone.utc) - created_at) < timedelta(minutes=1)


def test_two_accounts_get_different_ids(client):
    first = client.post("/accounts", json={"name": "test-first"}).json()
    second = client.post("/accounts", json={"name": "test-second"}).json()
    assert first["id"] != second["id"]


def test_database_connection_has_a_connect_timeout(monkeypatch):
    from app import db

    seen = {}
    monkeypatch.setattr(db.psycopg, "connect", lambda **kwargs: seen.update(kwargs))
    db.get_connection()
    assert seen["connect_timeout"] > 0
    # Waiting for a lock or running a statement is bounded too.
    assert "lock_timeout" in seen["options"] and "statement_timeout" in seen["options"]
