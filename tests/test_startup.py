import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_the_app_starts_when_the_settings_are_present():
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("name", ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"])
def test_the_app_refuses_to_start_when_a_setting_is_missing(monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(RuntimeError) as caught:
        with TestClient(app):
            pass
    assert name in str(caught.value)


def test_the_startup_error_does_not_show_setting_values(monkeypatch):
    monkeypatch.delenv("DB_HOST")
    monkeypatch.setenv("DB_PASSWORD", "hunter2-not-a-real-password")
    with pytest.raises(RuntimeError) as caught:
        with TestClient(app):
            pass
    assert "hunter2" not in str(caught.value)
