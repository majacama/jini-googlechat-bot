import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.chat_client import FakeChatClient
from app.dependencies import get_chat_client, get_repo
from app.main import app
from app.routers.chat import parse_chat_event
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


def test_start_accepts_conversation_json_and_recipient() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    settings.start_endpoint_token = "tok"
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_chat_client] = lambda: chat
    spec = json.loads(
        (
            Path(__file__).resolve().parent.parent / "forms" / "nouveau-dossier-client.json"
        ).read_text(encoding="utf-8")
    )
    try:
        client = TestClient(app)
        response = client.post(
            "/start",
            json={"form_spec": spec, "webhook_url": "https://example.test/ingest"},
            headers={"Authorization": "Bearer tok"},
        )
        assert response.status_code == 202
        space_id = response.json()["space_id"]
        stored = repo.get(space_id)
        assert stored is not None
        assert stored.phase == "interlocutor"
        assert stored.contact.user_email == "fdiaz@jin.fr"
        assert "Jin Investigator Agent" in chat.messages[0][1]
        assert "nom_dossier" not in (stored.current_field_id or "")

        reply = client.post(
            "/chat",
            json={
                "type": "MESSAGE",
                "space": {"name": space_id},
                "message": {"text": "oui"},
            },
        )
        assert reply.status_code == 200
        after = repo.get(space_id)
        assert after is not None
        assert after.phase == "questionnaire"
        assert after.current_field_id == "creation_dossier"
    finally:
        app.dependency_overrides.clear()


def test_start_refuses_when_session_already_active(form_spec) -> None:
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
        first = client.post("/start", json=payload, headers={"Authorization": "Bearer tok"})
        assert first.status_code == 202

        second = client.post("/start", json=payload, headers={"Authorization": "Bearer tok"})
        assert second.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_start_reuses_channel_once_previous_session_finished(form_spec) -> None:
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
        first = client.post("/start", json=payload, headers={"Authorization": "Bearer tok"})
        space_id = first.json()["space_id"]
        first_session_id = repo.get(space_id).session_id  # type: ignore[union-attr]

        # La session se termine (abandon, sans passer par tout le questionnaire).
        state = repo.get(space_id)
        assert state is not None
        state.status = "abandoned"
        repo.save(state)
        assert repo.get(space_id) is None  # canal libéré

        second = client.post("/start", json=payload, headers={"Authorization": "Bearer tok"})
        assert second.status_code == 202
        new_state = repo.get(space_id)
        assert new_state is not None
        assert new_state.session_id != first_session_id
        # l'ancienne session reste consultable pour l'historique
        assert repo.get_session(space_id, first_session_id) is not None
    finally:
        app.dependency_overrides.clear()


def test_parse_chat_event_addon_envelope() -> None:
    event_type, space_id, message = parse_chat_event(
        {
            "chat": {
                "messagePayload": {
                    "space": {"name": "spaces/AAA"},
                    "message": {"text": "Acme SAS", "sender": {"type": "HUMAN"}},
                }
            }
        }
    )
    assert event_type == "MESSAGE"
    assert space_id == "spaces/AAA"
    assert message["text"] == "Acme SAS"
