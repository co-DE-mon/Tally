import pytest

from test_transactions import create_account, post_transaction


def stored_state(client, account_id):
    history = client.get(f"/accounts/{account_id}/transactions").json()["data"]
    balance = client.get(f"/accounts/{account_id}/balance").json()["balance"]
    return history, balance


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("suffix", ["", "/{transaction_id}"])
def test_edit_and_delete_requests_are_refused_and_change_nothing(client, method, suffix):
    account_id = create_account(client)
    created = post_transaction(client, account_id).json()
    before = stored_state(client, account_id)

    url = f"/accounts/{account_id}/transactions" + suffix.format(transaction_id=created["id"])
    response = client.request(method, url, json={"amount": "999.00", "type": "debit"})

    assert response.status_code in (404, 405)
    assert "error" in response.json()
    assert stored_state(client, account_id) == before


def test_a_stored_transaction_reads_back_exactly_as_created(client):
    account_id = create_account(client)
    created = post_transaction(
        client, account_id, amount="12.30", description="rent", reference_id="ref-x"
    ).json()
    stored = client.get(f"/accounts/{account_id}/transactions").json()["data"][0]
    for field in ("id", "account_id", "type", "amount", "description", "reference_id", "created_at"):
        assert stored[field] == created[field]


def test_resubmitting_a_reference_id_with_new_values_does_not_edit_the_original(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="10.00", description="first", reference_id="same")
    before = stored_state(client, account_id)

    again = post_transaction(
        client, account_id, type="debit", amount="1.00", description="changed", reference_id="same"
    )

    assert again.status_code == 409
    assert stored_state(client, account_id) == before


def test_the_api_exposes_no_update_or_delete_operation():
    from app.main import app

    methods = {m for ops in app.openapi()["paths"].values() for m in ops}
    assert methods <= {"get", "post"}
