import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.db import get_connection
from app.repositories import accounts as accounts_repository

def create_account(client, name="test-account"):
    return client.post("/accounts", json={"name": name}).json()["id"]


def post_transaction(client, account_id, **overrides):
    body = {
        "type": "credit",
        "amount": "50.00",
        "description": "deposit",
        "reference_id": "ref-1",
    }
    body.update(overrides)
    return client.post(f"/accounts/{account_id}/transactions", json=body)


def test_credit_increases_balance(client):
    account_id = create_account(client)
    response = post_transaction(client, account_id)
    assert response.status_code == 201
    body = response.json()
    assert body["account_id"] == account_id
    assert body["type"] == "credit"
    assert body["amount"] == "50.00"
    assert body["description"] == "deposit"
    assert body["reference_id"] == "ref-1"
    assert body["balance"] == "50.00"
    UUID(body["id"])  # raises ValueError if the server did not return a valid UUID
    assert body["created_at"]


def test_debit_decreases_balance(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="100.00", reference_id="ref-1")
    response = post_transaction(
        client, account_id, type="debit", amount="30.00", reference_id="ref-2"
    )
    assert response.status_code == 201
    assert response.json()["balance"] == "70.00"


def test_overdraw_is_refused_and_changes_nothing(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="100.00", reference_id="ref-1")
    response = post_transaction(
        client, account_id, type="debit", amount="100.01", reference_id="ref-2"
    )
    assert response.status_code == 422
    # Same reference_id is reusable: the rejected debit left no row behind.
    retry = post_transaction(
        client, account_id, type="debit", amount="100.00", reference_id="ref-2"
    )
    assert retry.status_code == 201
    assert retry.json()["balance"] == "0.00"


def test_duplicate_reference_is_rejected_and_changes_nothing(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="50.00", reference_id="ref-1")
    response = post_transaction(client, account_id, amount="50.00", reference_id="ref-1")
    assert response.status_code == 409
    # The duplicate added no money: the next credit sees 50 + 10, not 100 + 10.
    after = post_transaction(client, account_id, amount="10.00", reference_id="ref-2")
    assert after.json()["balance"] == "60.00"


def test_same_reference_is_allowed_on_another_account(client):
    first = create_account(client, name="test-first")
    second = create_account(client, name="test-second")
    post_transaction(client, first, reference_id="shared-ref")
    response = post_transaction(client, second, reference_id="shared-ref")
    assert response.status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "0"},
        {"amount": "-5.00"},
        {"amount": "10.005"},
        {"amount": "10000000000000000.00"},
        {"reference_id": "   "},
        {"reference_id": "r" * 101},
        {"description": "d" * 256},
        {"description": "a\u0000b"},
        {"reference_id": "a\u0000b"},
    ],
)
def test_invalid_input_is_rejected_and_changes_nothing(client, overrides):
    account_id = create_account(client)
    response = post_transaction(client, account_id, **overrides)
    assert response.status_code == 422
    # Nothing was stored: a valid request with the same reference_id succeeds.
    ok = post_transaction(client, account_id, reference_id="ref-1", amount="1.00")
    assert ok.status_code == 201
    assert ok.json()["balance"] == "1.00"


def test_limits_are_accepted_at_the_boundary(client):
    account_id = create_account(client)
    response = post_transaction(
        client, account_id, reference_id="r" * 100, description="d" * 255
    )
    assert response.status_code == 201


def test_unknown_account_returns_404_and_stores_nothing(client):
    unknown_id = "00000000-0000-4000-8000-000000000000"
    response = post_transaction(client, unknown_id)
    assert response.status_code == 404


def test_malformed_account_id_returns_422(client):
    response = post_transaction(client, "not-a-uuid")
    assert response.status_code == 422


def test_credit_past_the_balance_limit_is_refused_and_changes_nothing(client):
    account_id = create_account(client)
    biggest = "9999999999999999.99"
    post_transaction(client, account_id, amount=biggest, reference_id="ref-1")
    response = post_transaction(client, account_id, amount="0.01", reference_id="ref-2")
    assert response.status_code == 422
    # Nothing changed: the same reference_id is free, and a debit sees the old balance.
    debit = post_transaction(
        client, account_id, type="debit", amount="0.01", reference_id="ref-2"
    )
    assert debit.status_code == 201
    assert debit.json()["balance"] == "9999999999999999.98"


def read_account(account_id):
    with get_connection() as conn:
        balance = conn.execute(
            "SELECT balance FROM accounts WHERE id = %s", (account_id,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT count(*) FROM transactions WHERE account_id = %s", (account_id,)
        ).fetchone()[0]
    return str(balance), rows


def test_failure_after_the_insert_rolls_the_insert_back(client, monkeypatch):
    account_id = create_account(client)

    def fail(*args, **kwargs):
        raise RuntimeError("database died between the insert and the balance update")

    monkeypatch.setattr(accounts_repository, "add_to_balance", fail)
    with pytest.raises(RuntimeError):
        post_transaction(client, account_id)
    assert read_account(account_id) == ("0.00", 0)


def test_concurrent_debits_never_overdraw(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="100.00", reference_id="seed")

    def debit(n):
        return post_transaction(
            client, account_id, type="debit", amount="30.00", reference_id=f"d-{n}"
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = sorted(pool.map(debit, range(8)))
    # 100 pays for exactly three debits of 30; the other five are refused.
    assert statuses == [201] * 3 + [422] * 5
    assert read_account(account_id) == ("10.00", 4)


def test_concurrent_duplicates_create_one_transaction(client):
    account_id = create_account(client)

    def credit(_):
        return post_transaction(
            client, account_id, amount="5.00", reference_id="same"
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = sorted(pool.map(credit, range(8)))
    assert statuses == [201] + [409] * 7
    assert read_account(account_id) == ("5.00", 1)


@pytest.mark.parametrize("bad_type", ["Credit", "DEBIT", "refund", ""])
def test_type_must_be_exactly_credit_or_debit(client, bad_type):
    account_id = create_account(client)
    assert post_transaction(client, account_id, type=bad_type).status_code == 422


def test_missing_reference_id_is_rejected(client):
    account_id = create_account(client)
    response = client.post(
        f"/accounts/{account_id}/transactions", json={"type": "credit", "amount": "5.00"}
    )
    assert response.status_code == 422


def test_missing_description_is_accepted_as_empty(client):
    account_id = create_account(client)
    response = client.post(
        f"/accounts/{account_id}/transactions",
        json={"type": "credit", "amount": "5.00", "reference_id": "ref-1"},
    )
    assert response.status_code == 201
    assert response.json()["description"] == ""


def test_ten_credits_of_a_tenth_make_exactly_one(client):
    account_id = create_account(client)
    for n in range(10):
        response = post_transaction(
            client, account_id, amount="0.10", reference_id=f"ref-{n}"
        )
    assert response.json()["balance"] == "1.00"


def test_a_tenth_plus_two_tenths_is_exactly_three_tenths(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="0.1", reference_id="ref-1")
    response = post_transaction(client, account_id, amount="0.2", reference_id="ref-2")
    assert response.json()["balance"] == "0.30"


def test_the_largest_amount_is_stored_without_rounding(client):
    account_id = create_account(client)
    response = post_transaction(client, account_id, amount="9999999999999999.99")
    assert response.status_code == 201
    assert response.json()["balance"] == "9999999999999999.99"


def test_new_account_balance_is_zero(client):
    account_id = create_account(client)
    response = client.get(f"/accounts/{account_id}/balance")
    assert response.status_code == 200
    assert response.json() == {"account_id": account_id, "balance": "0.00"}


def test_balance_after_credits_and_debits(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="100.00", reference_id="ref-1")
    post_transaction(client, account_id, amount="50.00", reference_id="ref-2")
    post_transaction(client, account_id, type="debit", amount="30.00", reference_id="ref-3")
    post_transaction(client, account_id, type="debit", amount="20.00", reference_id="ref-4")
    response = client.get(f"/accounts/{account_id}/balance")
    assert response.status_code == 200
    assert response.json() == {"account_id": account_id, "balance": "100.00"}


def test_balance_of_unknown_account_is_404(client):
    response = client.get(f"/accounts/{uuid4()}/balance")
    assert response.status_code == 404


def test_balance_with_malformed_account_id_is_422(client):
    response = client.get("/accounts/not-a-uuid/balance")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "amount,expected",
    [(100, "100.00"), (100.5, "100.50"), (0.1, "0.10"), ("10", "10.00"), ("10.50", "10.50")],
)
def test_exact_amounts_are_accepted_as_numbers_or_plain_strings(client, amount, expected):
    account_id = create_account(client)
    response = post_transaction(client, account_id, amount=amount)
    assert response.status_code == 201
    assert response.json()["amount"] == expected


@pytest.mark.parametrize(
    "amount",
    [1234567890123456.78, True, None, [5], "1_0", " 5 ", "1e2", "1E2", "+5", "5.", ".5", "-5.00", "",
     "\u0663", "\uff15.\uff10\uff10"],
)
def test_amounts_that_could_be_altered_or_misread_are_rejected(client, amount):
    account_id = create_account(client)
    response = post_transaction(client, account_id, amount=amount)
    assert response.status_code == 422
    # Nothing was stored: a valid request with the same reference_id succeeds.
    ok = post_transaction(client, account_id, amount="1.00")
    assert ok.status_code == 201
    assert ok.json()["balance"] == "1.00"


def test_reference_id_is_trimmed_before_the_duplicate_check(client):
    account_id = create_account(client)
    assert post_transaction(client, account_id, reference_id="ref-1").status_code == 201
    assert post_transaction(client, account_id, reference_id=" ref-1 ").status_code == 409


def test_reference_ids_are_case_sensitive(client):
    account_id = create_account(client)
    assert post_transaction(client, account_id, reference_id="ref-1").status_code == 201
    assert post_transaction(client, account_id, reference_id="REF-1").status_code == 201


def test_created_at_is_taken_after_the_account_lock(client):
    # Hold the account's row lock from a second connection. A request that waits
    # for it must get a created_at from after the lock was released, so history
    # order matches the order in which balances were applied.
    account_id = create_account(client)
    holder = get_connection()
    holder.execute("SELECT 1 FROM accounts WHERE id = %s FOR UPDATE", (account_id,))
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(post_transaction, client, account_id)
        time.sleep(0.5)
        released_at = holder.execute("SELECT clock_timestamp()").fetchone()[0]
        holder.commit()
        holder.close()
        response = waiting.result(timeout=10)
    assert response.status_code == 201
    created_at = datetime.fromisoformat(response.json()["created_at"])
    assert created_at >= released_at


def test_crediting_one_account_leaves_another_untouched(client):
    first = create_account(client, name="test-first")
    second = create_account(client, name="test-second")
    post_transaction(client, first, amount="50.00")
    assert client.get(f"/accounts/{first}/balance").json()["balance"] == "50.00"
    assert client.get(f"/accounts/{second}/balance").json()["balance"] == "0.00"
    assert client.get(f"/accounts/{second}/transactions").json()["total_records"] == 0


def test_a_duplicate_that_would_also_overdraw_is_a_duplicate(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="100.00", reference_id="seed")
    post_transaction(client, account_id, type="debit", amount="100.00", reference_id="d-1")
    # Replaying the debit would overdraw (balance is 0), but it is first a duplicate.
    again = post_transaction(client, account_id, type="debit", amount="100.00", reference_id="d-1")
    assert again.status_code == 409


def test_client_supplied_id_created_at_and_balance_are_ignored(client):
    account_id = create_account(client)
    response = client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "type": "credit", "amount": "1.00", "reference_id": "ref-1",
            "id": "00000000-0000-4000-8000-000000000001",
            "created_at": "2000-01-01T00:00:00Z", "balance": "999.00",
        },
    )
    body = response.json()
    assert response.status_code == 201
    assert body["id"] != "00000000-0000-4000-8000-000000000001"
    assert body["created_at"].startswith(str(datetime.now().year))
    assert body["balance"] == "1.00"


def test_a_held_lock_gives_503_and_stores_nothing(client, monkeypatch):
    from app import db

    account_id = create_account(client)
    monkeypatch.setattr(db, "LOCK_TIMEOUT_MS", 300)
    holder = get_connection()
    holder.execute("SELECT 1 FROM accounts WHERE id = %s FOR UPDATE", (account_id,))
    started = time.monotonic()
    try:
        response = post_transaction(client, account_id)
    finally:
        holder.rollback()
        holder.close()
    assert time.monotonic() - started < 5
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "retry-after" in response.headers
    assert client.get(f"/accounts/{account_id}/transactions").json()["total_records"] == 0


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", '"NaN"', '"Infinity"', "1e400", '"1e400"'])
def test_non_finite_and_overflowing_amounts_are_rejected(client, amount):
    account_id = create_account(client)
    response = client.post(
        f"/accounts/{account_id}/transactions",
        content='{"type":"credit","amount":%s,"reference_id":"ref-1"}' % amount,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert client.get(f"/accounts/{account_id}/transactions").json()["total_records"] == 0
