from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.auth import CHAT_ISSUER, verify_chat_jwt
from app.main import app


def test_chat_allows_unauthenticated_when_disabled() -> None:
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.post("/chat", json={"type": "MESSAGE", "space": {"name": "spaces/x"}})
    assert response.status_code == 200


def test_chat_rejects_missing_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_AUTH_DISABLED", "0")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("CHAT_AUDIENCE", "https://example.test/chat")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        response = client.post("/chat", json={"type": "MESSAGE"})
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_chat_rejects_invalid_jwt_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_AUTH_DISABLED", "0")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("CHAT_AUDIENCE", "https://example.test/chat")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        response = client.post(
            "/chat",
            json={"type": "MESSAGE"},
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_chat_accepts_verified_jwt(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_AUTH_DISABLED", "0")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("CHAT_AUDIENCE", "https://example.test/chat")
    get_settings.cache_clear()

    def _fake_jwt(_token: str) -> dict:
        return {"email": CHAT_ISSUER, "iss": CHAT_ISSUER, "aud": "https://example.test/chat"}

    monkeypatch.setattr("app.core.auth.verify_chat_jwt", _fake_jwt)
    try:
        client = TestClient(app)
        response = client.post(
            "/chat",
            json={"type": "MESSAGE", "space": {"name": "spaces/x"}},
            headers={"Authorization": "Bearer fake"},
        )
        assert response.status_code == 200
    finally:
        get_settings.cache_clear()


def test_verify_chat_jwt_requires_audience_or_app_id(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_AUDIENCE", "")
    monkeypatch.setenv("GOOGLE_CHAT_APP_ID", "")
    get_settings.cache_clear()
    try:
        try:
            verify_chat_jwt("token")
            raise AssertionError("expected RuntimeError")
        except RuntimeError:
            pass
    finally:
        get_settings.cache_clear()
