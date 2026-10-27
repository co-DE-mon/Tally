from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import accounts as accounts_service
from test_transactions import create_account, post_transaction


def assert_error(response, status, code):
    # One shape for every error: {"error": {"code": ..., "message": ...}}.
    assert response.status_code == status
    body = response.json()
    assert list(body) == ["error"]
    assert sorted(body["error"]) == ["code", "message"]
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    return body["error"]["message"]


@pytest.mark.parametrize(
    "method,suffix", [("POST", "transactions"), ("GET", "balance"), ("GET", "transactions")]
)
def test_account_not_found(client, method, suffix):
    body = {"type": "credit", "amount": "1.00", "reference_id": "ref-1"}
    response = client.request(method, f"/accounts/{uuid4()}/{suffix}", json=body)
    assert_error(response, 404, "ACCOUNT_NOT_FOUND")


def test_invalid_transaction_type(client):
    account_id = create_account(client)
    response = post_transaction(client, account_id, type="refund")
    assert "type" in assert_error(response, 422, "VALIDATION_ERROR")


def test_invalid_amount(client):
    account_id = create_account(client)
    response = post_transaction(client, account_id, amount="0")
    assert "amount" in assert_error(response, 422, "VALIDATION_ERROR")


def test_insufficient_balance(client):
    account_id = create_account(client)
    response = post_transaction(client, account_id, type="debit", amount="1.00")
    assert_error(response, 422, "INSUFFICIENT_BALANCE")


def test_balance_limit_exceeded(client):
    account_id = create_account(client)
    post_transaction(client, account_id, amount="9999999999999999.99", reference_id="a")
    response = post_transaction(client, account_id, amount="0.01", reference_id="b")
    assert_error(response, 422, "BALANCE_LIMIT_EXCEEDED")


def test_duplicate_transaction(client):
    account_id = create_account(client)
    post_transaction(client, account_id)
    assert_error(post_transaction(client, account_id), 409, "DUPLICATE_REFERENCE")


@pytest.mark.parametrize("params,field", [({"page": 0}, "page"), ({"limit": "abc"}, "limit")])
def test_invalid_pagination(client, params, field):
    account_id = create_account(client)
    response = client.get(f"/accounts/{account_id}/transactions", params=params)
    assert field in assert_error(response, 422, "VALIDATION_ERROR")


def test_invalid_request_body_missing_field(client):
    response = client.post("/accounts", json={})
    assert "name" in assert_error(response, 422, "VALIDATION_ERROR")


def test_invalid_request_body_malformed_json(client):
    response = client.post(
        "/accounts", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert_error(response, 422, "VALIDATION_ERROR")


def test_malformed_account_id(client):
    response = client.get("/accounts/not-a-uuid/balance")
    assert "account_id" in assert_error(response, 422, "VALIDATION_ERROR")


def test_unknown_route(client):
    assert_error(client.get("/nowhere"), 404, "NOT_FOUND")


def test_method_not_allowed(client):
    account_id = create_account(client)
    response = client.delete(f"/accounts/{account_id}/transactions")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")


def test_unexpected_error_is_a_generic_500_and_leaks_nothing(monkeypatch):
    def explode(name):
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(accounts_service, "create_account", explode)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/accounts", json={"name": "test-boom"}
    )
    message = assert_error(response, 500, "INTERNAL_ERROR")
    assert "secret" not in message and "secret" not in response.text


def test_method_not_allowed_carries_an_allow_header(client):
    account_id = create_account(client)
    response = client.delete(f"/accounts/{account_id}/transactions")
    assert response.status_code == 405
    # Starlette lists the methods of the first matching route, so this may be only POST.
    allowed = {m.strip() for m in response.headers["allow"].split(",")}
    assert allowed and allowed <= {"GET", "POST"}


def error_schema_names(operation, status):
    schema = operation["responses"][status]["content"]["application/json"]["schema"]
    return schema["$ref"].rsplit("/", 1)[-1]


@pytest.mark.parametrize(
    "path,method,statuses",
    [
        ("/accounts", "post", ["422", "500", "503"]),
        ("/accounts/{account_id}/balance", "get", ["404", "422", "500", "503"]),
        ("/accounts/{account_id}/transactions", "get", ["404", "422", "500", "503"]),
        ("/accounts/{account_id}/transactions", "post", ["404", "409", "422", "500", "503"]),
        ("/transfers", "post", ["404", "409", "422", "500", "503"]),
    ],
)
def test_openapi_documents_the_real_error_body(path, method, statuses):
    operation = app.openapi()["paths"][path][method]
    for status in statuses:
        assert error_schema_names(operation, status) == "ErrorResponse"


def test_openapi_does_not_describe_fastapis_default_error_body():
    assert "HTTPValidationError" not in app.openapi()["components"]["schemas"]
