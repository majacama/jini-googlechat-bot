import json
from pathlib import Path

from app.core.chat_client import FakeChatClient
from app.core.turn import begin_conversation, process_user_message
from app.models.form_spec import Contact, FormSpec
from app.storage.memory_repo import MemoryConversationRepo

FORMS = Path(__file__).resolve().parent.parent / "forms"


def _client_spec() -> FormSpec:
    data = json.loads((FORMS / "nouveau-dossier-client.json").read_text(encoding="utf-8"))
    return FormSpec.model_validate(data)


def test_field_values_prefill_skips_its_question_and_fills_placeholder() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    state = begin_conversation(
        contact=Contact(user_email="fdiaz@jin.fr"),
        form_spec=_client_spec(),
        webhook_url="https://example.test/ingest",
        repo=repo,
        chat_client=chat,
        field_values={"nom_dossier": "_sephora"},
    )
    assert state.answers["nom_dossier"] == "_sephora"
    # Le placeholder de la question d'interlocuteur est déjà résolu à l'ouverture.
    assert "_sephora" in chat.messages[0][1]
    assert "{{nom_dossier}}" not in chat.messages[0][1]

    process_user_message(state.space_id, "oui", repo, chat)  # interlocuteur : oui
    process_user_message(state.space_id, "oui", repo, chat)  # creation_dossier : oui
    current = repo.get(state.space_id)
    assert current is not None
    # nom_dossier déjà connu -> on saute directement à niveau_securite
    assert current.current_field_id == "niveau_securite"


def test_field_values_invalid_is_ignored_question_still_asked() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    state = begin_conversation(
        contact=Contact(user_email="fdiaz@jin.fr"),
        form_spec=_client_spec(),
        webhook_url="https://example.test/ingest",
        repo=repo,
        chat_client=chat,
        field_values={"nom_dossier": "PasDeUnderscore"},  # ne respecte pas le pattern
    )
    assert "nom_dossier" not in state.answers
    # Placeholder non résolu -> laissé vide, pas planté ni laissé en {{...}}.
    assert "{{nom_dossier}}" not in chat.messages[0][1]


def test_field_values_unknown_field_is_ignored() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    state = begin_conversation(
        contact=Contact(user_email="fdiaz@jin.fr"),
        form_spec=_client_spec(),
        webhook_url="https://example.test/ingest",
        repo=repo,
        chat_client=chat,
        field_values={"champ_inexistant": "x"},
    )
    assert "champ_inexistant" not in state.answers
