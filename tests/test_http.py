from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.chat_client import FakeChatClient
from app.dependencies import get_chat_client, get_repo
from app.main import app
from app.storage.memory_repo import MemoryConversationRepo


def test_health() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_start_requires_bearer(form_spec) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    settings.start_endpoint_token = "tok"
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_chat_client] = lambda: chat
    try:
        client = TestClient(app)
        payload = {
            "contact": {"user_email": "collaborateur@jin.fr"},
            "form_spec": form_spec.model_dump(),
            "webhook_url": "https://example.test/ingest",
        }
        assert client.post("/start", json=payload).status_code == 401
        response = client.post(
            "/start",
            json=payload,
            headers={"Authorization": "Bearer tok"},
        )
        assert response.status_code == 202
        space_id = response.json()["space_id"]
        assert space_id.startswith("spaces/")
        assert chat.messages
        stored = repo.get(space_id)
        assert stored is not None
        assert stored.form_id == form_spec.form_id

        reply = client.post(
            "/chat",
            json={
                "type": "MESSAGE",
                "space": {"name": space_id},
                "message": {"text": "Acme SAS"},
            },
        )
        assert reply.status_code == 200
        inspect = client.get(
            "/conversations",
            params={"space_id": space_id},
            headers={"Authorization": "Bearer tok"},
        )
        assert inspect.status_code == 200
        body = inspect.json()
        assert body["answers"]["nom_fournisseur"] == "Acme SAS"
        assert body["current_field_id"] == "date_debut"
        assert "webhook_secret" not in body

        bot_echo = client.post(
            "/chat",
            json={
                "type": "MESSAGE",
                "space": {"name": space_id},
                "message": {
                    "text": "Question agent",
                    "sender": {"type": "BOT"},
                },
            },
        )
        assert bot_echo.status_code == 200
        still = repo.get(space_id)
        assert still is not None
        assert still.current_field_id == "date_debut"
    finally:
        app.dependency_overrides.clear()
