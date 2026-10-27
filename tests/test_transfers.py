from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db import get_connection
from app.repositories import accounts as accounts_repository
from test_transactions import create_account, post_transaction


def fund(client, account_id, amount):
    assert post_transaction(client, account_id, amount=amount, reference_id="fund").status_code == 201


def transfer(client, source, destination, **overrides):
    body = {
        "source_account_id": source,
        "destination_account_id": destination,
        "amount": "30.00",
        "description": "move",
        "reference_id": "t-1",
    }
    body.update(overrides)
    return client.post("/transfers", json=body)


def balance(client, account_id):
    return client.get(f"/accounts/{account_id}/balance").json()["balance"]


def rows(client, account_id):
    return client.get(f"/accounts/{account_id}/transactions?limit=100").json()["data"]


def pair(client):
    a = create_account(client, name="test-a")
    b = create_account(client, name="test-b")
    fund(client, a, "100.00")
    fund(client, b, "50.00")
    return a, b


def assert_untouched(client, a, b):
    assert (balance(client, a), balance(client, b)) == ("100.00", "50.00")
    assert len(rows(client, a)) == 1 and len(rows(client, b)) == 1  # only the funding rows


def test_a_transfer_moves_money_and_returns_both_legs(client):
    a, b = pair(client)
    response = transfer(client, a, b)
    assert response.status_code == 201
    body = response.json()
    debit, credit = body["debit"], body["credit"]
    assert (debit["type"], debit["account_id"], debit["amount"], debit["balance"]) == ("debit", a, "30.00", "70.00")
    assert (credit["type"], credit["account_id"], credit["amount"], credit["balance"]) == ("credit", b, "30.00", "80.00")
    assert debit["transfer_id"] == credit["transfer_id"] == body["transfer_id"]
    assert debit["id"] != credit["id"]
    assert debit["reference_id"] == credit["reference_id"] == "t-1"
    assert (balance(client, a), balance(client, b)) == ("70.00", "80.00")


def test_each_account_history_shows_its_own_leg(client):
    a, b = pair(client)
    transfer_id = transfer(client, a, b).json()["transfer_id"]
    source_leg = rows(client, a)[0]
    destination_leg = rows(client, b)[0]
    assert (source_leg["type"], source_leg["transfer_id"]) == ("debit", transfer_id)
    assert (destination_leg["type"], destination_leg["transfer_id"]) == ("credit", transfer_id)


def test_ordinary_transactions_have_no_transfer_id(client):
    account_id = create_account(client)
    created = post_transaction(client, account_id).json()
    assert created["transfer_id"] is None
    assert rows(client, account_id)[0]["transfer_id"] is None


def test_insufficient_funds_changes_nothing(client):
    a, b = pair(client)
    response = transfer(client, a, b, amount="100.01")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert_untouched(client, a, b)


def test_the_whole_balance_can_be_transferred(client):
    a, b = pair(client)
    assert transfer(client, a, b, amount="100.00").status_code == 201
    assert (balance(client, a), balance(client, b)) == ("0.00", "150.00")


@pytest.mark.parametrize("missing", ["source", "destination"])
def test_a_missing_account_changes_nothing(client, missing):
    a, b = pair(client)
    ghost = str(uuid4())
    response = transfer(client, ghost, b) if missing == "source" else transfer(client, a, ghost)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert_untouched(client, a, b)


def test_a_transfer_to_the_same_account_is_rejected(client):
    a, b = pair(client)
    response = transfer(client, a, a)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SAME_ACCOUNT"
    assert_untouched(client, a, b)


def test_a_repeated_reference_id_is_a_duplicate_and_changes_nothing(client):
    a, b = pair(client)
    assert transfer(client, a, b).status_code == 201
    again = transfer(client, a, b)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "DUPLICATE_REFERENCE"
    assert (balance(client, a), balance(client, b)) == ("70.00", "80.00")
    assert len(rows(client, a)) == 2 and len(rows(client, b)) == 2


def test_a_reference_already_used_on_the_destination_rolls_back_the_source_leg(client):
    a, b = pair(client)
    post_transaction(client, b, amount="1.00", reference_id="t-1")  # b already uses t-1
    response = transfer(client, a, b)
    assert response.status_code == 409
    assert balance(client, a) == "100.00"          # the debit leg was rolled back
    assert len(rows(client, a)) == 1


def test_a_failure_in_the_credit_leg_rolls_back_the_debit_leg(client, monkeypatch):
    a, b = pair(client)
    real = accounts_repository.add_to_balance
    calls = []

    def fail_on_second_call(conn, account_id, delta):
        calls.append(account_id)
        if len(calls) == 2:
            raise RuntimeError("database died between the two balance updates")
        return real(conn, account_id, delta)

    monkeypatch.setattr(accounts_repository, "add_to_balance", fail_on_second_call)
    with pytest.raises(RuntimeError):
        transfer(client, a, b)
    assert len(calls) == 2
    assert_untouched(client, a, b)


def test_a_credit_past_the_balance_limit_changes_nothing(client):
    a = create_account(client, name="test-a")
    b = create_account(client, name="test-b")
    fund(client, a, "10.00")
    post_transaction(client, b, amount="9999999999999999.99", reference_id="max")
    response = transfer(client, a, b, amount="1.00")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BALANCE_LIMIT_EXCEEDED"
    assert (balance(client, a), balance(client, b)) == ("10.00", "9999999999999999.99")


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "0"}, {"amount": "-1.00"}, {"amount": "1.005"}, {"amount": "abc"},
        {"reference_id": "  "}, {"reference_id": "x" * 101}, {"description": "d" * 256},
        {"source_account_id": "not-a-uuid"}, {"destination_account_id": "not-a-uuid"},
    ],
)
def test_invalid_input_is_rejected_and_changes_nothing(client, overrides):
    a, b = pair(client)
    response = transfer(client, a, b, **overrides)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_untouched(client, a, b)


@pytest.mark.parametrize("field", ["source_account_id", "destination_account_id", "amount", "reference_id"])
def test_required_fields(client, field):
    a, b = pair(client)
    body = {"source_account_id": a, "destination_account_id": b, "amount": "1.00", "reference_id": "t-9"}
    del body[field]
    assert client.post("/transfers", json=body).status_code == 422
    assert_untouched(client, a, b)


def test_a_missing_description_is_stored_empty_and_extra_fields_are_ignored(client):
    a, b = pair(client)
    response = client.post("/transfers", json={
        "source_account_id": a, "destination_account_id": b, "amount": "5.00", "reference_id": "t-2",
        "type": "credit", "balance": "999", "id": str(uuid4()),
    })
    assert response.status_code == 201
    assert response.json()["debit"]["description"] == ""
    assert response.json()["debit"]["type"] == "debit"


def test_opposite_transfers_at_the_same_time_do_not_deadlock(client):
    a = create_account(client, name="test-a")
    b = create_account(client, name="test-b")
    fund(client, a, "1000.00")
    fund(client, b, "1000.00")

    def move(n):
        source, destination = (a, b) if n % 2 == 0 else (b, a)
        return transfer(client, source, destination, amount="7.50", reference_id=f"c-{n}").status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(move, range(60)))
    assert set(statuses) == {201}
    # Thirty each way cancels out, and no money was created or lost.
    assert (balance(client, a), balance(client, b)) == ("1000.00", "1000.00")


def test_concurrent_transfers_never_overdraw_the_source(client):
    a, b = pair(client)

    def move(n):
        return transfer(client, a, b, amount="30.00", reference_id=f"c-{n}").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = sorted(pool.map(move, range(8)))
    assert statuses == [201] * 3 + [422] * 5          # 100 pays for three transfers of 30
    assert (balance(client, a), balance(client, b)) == ("10.00", "140.00")


def test_total_money_is_conserved_and_balances_match_history(client):
    a, b = pair(client)
    for n in range(5):
        transfer(client, a, b, amount="3.33", reference_id=f"m-{n}")
        transfer(client, b, a, amount="1.11", reference_id=f"r-{n}")
    assert Decimal(balance(client, a)) + Decimal(balance(client, b)) == Decimal("150.00")
    for account_id in (a, b):
        total = sum(
            Decimal(r["amount"]) * (1 if r["type"] == "credit" else -1) for r in rows(client, account_id)
        )
        assert Decimal(balance(client, account_id)) == total


def test_the_transfer_legs_share_a_transfer_id_in_the_database(client):
    a, b = pair(client)
    transfer_id = transfer(client, a, b).json()["transfer_id"]
    with get_connection() as conn:
        found = conn.execute(
            "SELECT count(*), count(DISTINCT account_id) FROM transactions WHERE transfer_id = %s",
            (transfer_id,),
        ).fetchone()
    assert found == (2, 2)
