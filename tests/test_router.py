import pytest

from app.core.chat_client import FakeChatClient
from app.core.turn import process_user_message
from app.kb.answer import KbAnswer
from app.kb.types import KbHit
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


def test_cold_message_search_knowledge_base_without_results_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import turn as turn_module

    monkeypatch.setattr(
        turn_module,
        "answer_from_knowledge_base",
        lambda q, h=None: KbAnswer("Je n'ai rien trouvé dans les documents JIN pour cette question."),
    )
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
    assert "rien trouvé" in chat.messages[-1][1].lower()
    assert chat.cards_sent[-1] is None


def test_cold_message_search_knowledge_base_sends_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import turn as turn_module
    hit = KbHit("f1", "Contrat cadre Sephora", "https://drive.google.com/x", 0, "...", 0.8)
    monkeypatch.setattr(
        turn_module, "answer_from_knowledge_base", lambda q, h=None: KbAnswer("Oui, un contrat cadre existe.", [hit], True)
    )
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(
        SPACE_ID,
        "est-ce qu'on a déjà un contrat cadre avec Sephora ?",
        repo,
        chat,
        sender=SENDER_WITH_EMAIL,
    )
    assert repo.get(SPACE_ID) is None  # le RAG ne demarre pas de session
    assert chat.cards_sent[-1] is not None
    assert chat.cards_sent[-1][0]["card"]["header"]["title"] == "Contrat cadre Sephora"


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


def test_follow_up_question_receives_previous_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import turn as turn_module
    from app.models.route import RouteAction

    seen: list = []

    def fake_route(text, processes, recent=None):
        seen.append(recent)
        return RouteAction(action="search_knowledge_base", query=text, message_to_user="")

    monkeypatch.setattr(turn_module, "decide_route", fake_route)
    monkeypatch.setattr(
        turn_module, "answer_from_knowledge_base", lambda q, h=None: KbAnswer(f"réponse à {q}")
    )
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    process_user_message(SPACE_ID, "que dit la PSSI sur les mobiles ?", repo, chat, sender=SENDER_WITH_EMAIL)
    process_user_message(SPACE_ID, "et sur les appareils pro ?", repo, chat, sender=SENDER_WITH_EMAIL)
    assert seen[0] == []
    assert seen[1][0]["question"] == "que dit la PSSI sur les mobiles ?"
    assert "réponse à" in seen[1][0]["answer"]


def test_recent_qa_expires_and_is_capped() -> None:
    repo = MemoryConversationRepo()
    for i in range(6):
        repo.add_qa(SPACE_ID, f"q{i}", "a")
    assert [t["question"] for t in repo.get_recent_qa(SPACE_ID)] == ["q2", "q3", "q4", "q5"]
    repo._qa[next(iter(repo._qa))][0]["at"] = 0
    assert len(repo.get_recent_qa(SPACE_ID)) == 3
