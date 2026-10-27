from uuid import uuid4

import pytest

from app.db import get_connection
from app.repositories import transactions as transactions_repository
from test_transactions import create_account, post_transaction


def post(client, account_id, reference_id, **overrides):
    response = post_transaction(client, account_id, reference_id=reference_id, **overrides)
    assert response.status_code == 201
    return response.json()


def history(client, account_id, **params):
    return client.get(f"/accounts/{account_id}/transactions", params=params)


def references(response):
    return [row["reference_id"] for row in response.json()["data"]]


def test_no_type_returns_credits_and_debits(client):
    account_id = create_account(client)
    post(client, account_id, "c-1")
    post(client, account_id, "d-1", type="debit", amount="5.00")
    response = history(client, account_id)
    assert response.status_code == 200
    assert sorted(references(response)) == ["c-1", "d-1"]


@pytest.mark.parametrize("kind,expected", [("credit", ["c-2", "c-1"]), ("debit", ["d-1"])])
def test_type_filter_returns_only_that_type(client, kind, expected):
    account_id = create_account(client)
    post(client, account_id, "c-1")
    post(client, account_id, "d-1", type="debit", amount="5.00")
    post(client, account_id, "c-2")
    response = history(client, account_id, type=kind)
    assert references(response) == expected
    assert response.json()["total_records"] == len(expected)


def test_results_are_latest_first(client):
    account_id = create_account(client)
    for n in range(1, 4):
        post(client, account_id, f"ref-{n}")
    assert references(history(client, account_id)) == ["ref-3", "ref-2", "ref-1"]


def test_rows_with_the_same_created_at_are_ordered_by_id_descending(client):
    account_id = create_account(client)
    ids = [f"00000000-0000-4000-8000-00000000000{n}" for n in (1, 2, 3)]
    with get_connection() as conn:
        for n, row_id in enumerate(ids):
            conn.execute(
                "INSERT INTO transactions (id, account_id, type, amount, reference_id, created_at) "
                "VALUES (%s, %s, 'credit', 1, %s, '2026-01-01T00:00:00Z')",
                (row_id, account_id, f"tie-{n}"),
            )
    rows = history(client, account_id).json()["data"]
    assert [row["id"] for row in rows] == ids[::-1]


def test_pages_return_the_right_slice_and_metadata(client):
    account_id = create_account(client)
    for n in range(1, 6):
        post(client, account_id, f"ref-{n}")
    first = history(client, account_id, page=1, limit=2)
    second = history(client, account_id, page=2, limit=2)
    last = history(client, account_id, page=3, limit=2)
    assert references(first) == ["ref-5", "ref-4"]
    assert references(second) == ["ref-3", "ref-2"]
    assert references(last) == ["ref-1"]
    body = second.json()
    assert (body["page"], body["limit"]) == (2, 2)
    assert (body["total_records"], body["total_pages"]) == (5, 3)


def test_page_past_the_end_is_empty_not_an_error(client):
    account_id = create_account(client)
    post(client, account_id, "ref-1")
    response = history(client, account_id, page=9, limit=2)
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert (body["total_records"], body["total_pages"]) == (1, 1)


def test_empty_history_has_zero_pages(client):
    account_id = create_account(client)
    body = history(client, account_id).json()
    assert body["data"] == []
    assert (body["page"], body["limit"]) == (1, 20)
    assert (body["total_records"], body["total_pages"]) == (0, 0)


def test_total_records_counts_only_the_filtered_type(client):
    account_id = create_account(client)
    for n in range(3):
        post(client, account_id, f"c-{n}")
    post(client, account_id, "d-1", type="debit", amount="5.00")
    body = history(client, account_id, type="debit", limit=1).json()
    assert (body["total_records"], body["total_pages"]) == (1, 1)


def test_history_entries_carry_the_stored_fields_and_no_balance(client):
    account_id = create_account(client)
    created = post(client, account_id, "ref-1")
    row = history(client, account_id).json()["data"][0]
    assert row == {key: value for key, value in created.items() if key != "balance"}


def test_a_limit_above_the_maximum_is_clamped_with_a_header(client):
    account_id = create_account(client)
    response = history(client, account_id, limit=500)
    assert response.status_code == 200
    assert response.json()["limit"] == 100
    assert "100" in response.headers["X-Pagination-Warning"]


def test_a_limit_above_the_maximum_returns_only_the_maximum_rows(client):
    account_id = create_account(client)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO transactions (account_id, type, amount, reference_id) "
            "SELECT %s, 'credit', 1, 'g-' || n FROM generate_series(1, 101) n",
            (account_id,),
        )
    body = history(client, account_id, limit=500).json()
    assert len(body["data"]) == 100
    assert (body["limit"], body["total_records"], body["total_pages"]) == (100, 101, 2)


def test_a_limit_within_range_has_no_warning_header(client):
    account_id = create_account(client)
    assert "X-Pagination-Warning" not in history(client, account_id, limit=100).headers


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page": "abc"},
        {"page": 10**18},
        {"limit": 0},
        {"limit": -5},
        {"limit": "abc"},
        {"type": "refund"},
        {"type": "Credit"},
    ],
)
def test_invalid_query_values_are_rejected(client, params):
    account_id = create_account(client)
    response = history(client, account_id, **params)
    assert response.status_code == 422
    assert "error" in response.json()


def test_unknown_account_returns_404(client):
    assert history(client, str(uuid4())).status_code == 404


def test_malformed_account_id_returns_422(client):
    assert history(client, "not-a-uuid").status_code == 422


def test_a_rejected_debit_does_not_appear(client):
    account_id = create_account(client)
    post(client, account_id, "c-1", amount="10.00")
    refused = client.post(
        f"/accounts/{account_id}/transactions",
        json={"type": "debit", "amount": "99.00", "reference_id": "d-1"},
    )
    assert refused.status_code == 422
    assert references(history(client, account_id)) == ["c-1"]


def test_total_records_and_data_come_from_one_snapshot(client, monkeypatch):
    account_id = create_account(client)
    post(client, account_id, "ref-1")
    count = transactions_repository.count_transactions

    def count_then_commit_another(*args):
        total = count(*args)
        post(client, account_id, "ref-2")  # commits on its own connection
        return total

    monkeypatch.setattr(
        transactions_repository, "count_transactions", count_then_commit_another
    )
    body = history(client, account_id).json()
    assert body["total_records"] == len(body["data"]) == 1


def test_a_filtered_history_pages_with_matching_counts(client):
    account_id = create_account(client)
    for n in range(1, 6):
        post(client, account_id, f"c-{n}")
        post(client, account_id, f"d-{n}", type="debit", amount="1.00")
    first = history(client, account_id, type="credit", page=1, limit=2).json()
    last = history(client, account_id, type="credit", page=3, limit=2).json()
    assert [row["reference_id"] for row in first["data"]] == ["c-5", "c-4"]
    assert [row["reference_id"] for row in last["data"]] == ["c-1"]
    assert (first["total_records"], first["total_pages"]) == (5, 3)
    assert {row["type"] for row in first["data"] + last["data"]} == {"credit"}
