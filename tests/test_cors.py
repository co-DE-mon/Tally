PAGE_ORIGIN = "http://localhost:5500"


def preflight(client, origin):
    return client.options(
        "/accounts",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_testing_page_origin_is_allowed(client):
    response = preflight(client, PAGE_ORIGIN)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PAGE_ORIGIN


def test_other_origin_is_refused(client):
    response = preflight(client, "http://evil.example")
    assert "access-control-allow-origin" not in response.headers


def test_error_response_still_carries_the_header(client):
    response = client.post("/accounts", json={}, headers={"Origin": PAGE_ORIGIN})
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == PAGE_ORIGIN


def assert_json_rejection(response, message):
    # A rejected preflight uses the same error shape as every other error.
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"error": {"code": "CORS_REJECTED", "message": message}}


def test_rejected_preflight_origin_uses_the_error_shape(client):
    assert_json_rejection(preflight(client, "http://evil.example"), "Disallowed CORS origin")


def test_rejected_preflight_method_uses_the_error_shape(client):
    response = client.options(
        "/accounts",
        headers={"Origin": PAGE_ORIGIN, "Access-Control-Request-Method": "PUT"},
    )
    assert_json_rejection(response, "Disallowed CORS method")


def test_rejected_preflight_headers_use_the_error_shape(client):
    response = client.options(
        "/accounts",
        headers={
            "Origin": PAGE_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-custom",
        },
    )
    assert_json_rejection(response, "Disallowed CORS headers")


def test_accepted_preflight_is_unchanged(client):
    response = preflight(client, PAGE_ORIGIN)
    assert response.status_code == 200
    assert response.headers["access-control-allow-methods"] == "GET, POST"
