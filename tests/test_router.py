import pytest

from app.core.chat_client import FakeChatClient
from app.core.turn import process_user_message
from app.storage.memory_repo import MemoryConversationRepo

SPACE_ID = "spaces/AAAAcold"
SENDER_WITH_EMAIL = {
    "type": "HUMAN",
    "name": "users/113859878083610238922",
    "displayName": "Marie Martin",
    "email": "marie.martin@jin.fr",
}


def test_cold_message_starts_process_in_same_space() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(
        SPACE_ID,
        "il faut créer un nouveau dossier client pour Sephora",
        repo,
        chat,
        sender=SENDER_WITH_EMAIL,
    )
    state = repo.get(SPACE_ID)
    assert state is not None
    assert state.form_id == "nouveau-dossier-client-v1"
    assert state.contact.user_email == "marie.martin@jin.fr"
    # Pas de nouveau DM créé : on reste dans l'espace où le message est arrivé.
    assert chat.dms == []
    assert chat.messages
    assert chat.messages[0][0] == SPACE_ID


def test_cold_message_search_knowledge_base_is_a_placeholder_for_now() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(
        SPACE_ID,
        "est-ce qu'on a déjà un contrat cadre avec Sephora ?",
        repo,
        chat,
        sender=SENDER_WITH_EMAIL,
    )
    assert repo.get(SPACE_ID) is None  # aucune session démarrée
    assert "bientôt" in chat.messages[-1][1].lower() or "encore" in chat.messages[-1][1].lower()


def test_cold_message_empty_text_asks_for_clarification() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(SPACE_ID, "  ", repo, chat, sender=SENDER_WITH_EMAIL)
    assert repo.get(SPACE_ID) is None
    assert chat.messages


def test_cold_message_bot_sender_is_ignored() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(
        SPACE_ID,
        "crée un dossier client",
        repo,
        chat,
        sender={"type": "BOT"},
    )
    assert repo.get(SPACE_ID) is None
    assert chat.messages == []


def test_cold_message_without_resolvable_email_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import chat_client as chat_client_module

    monkeypatch.setattr(chat_client_module, "_directory_user_email", lambda user_id: None)
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(
        SPACE_ID,
        "il faut créer un nouveau dossier client",
        repo,
        chat,
        sender={"type": "HUMAN", "name": "users/999", "displayName": "Sans email"},
    )
    assert repo.get(SPACE_ID) is None
    assert "adresse e-mail" in chat.messages[-1][1]


def test_resolve_sender_email_prefers_direct_email() -> None:
    from app.core.chat_client import resolve_sender_email

    assert resolve_sender_email(SENDER_WITH_EMAIL) == "marie.martin@jin.fr"


def test_resolve_sender_email_falls_back_to_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import chat_client

    monkeypatch.setattr(chat_client, "_directory_user_email", lambda user_id: "found@jin.fr")
    result = chat_client.resolve_sender_email({"name": "users/42"})
    assert result == "found@jin.fr"


def test_resolve_sender_email_returns_none_without_name_or_email() -> None:
    from app.core.chat_client import resolve_sender_email

    assert resolve_sender_email({}) is None
