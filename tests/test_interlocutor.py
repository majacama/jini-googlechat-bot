import json
from pathlib import Path

from app.config import get_settings
from app.core.chat_client import FakeChatClient
from app.core.state_machine import apply_action, opening_message
from app.core.turn import begin_conversation, process_user_message
from app.models.conversation_state import AgentAction, ConversationState
from app.models.form_spec import Contact, FormSpec, derive_target_schema
from app.storage.memory_repo import MemoryConversationRepo

FORMS = Path(__file__).resolve().parent.parent / "forms"


def _client_spec() -> FormSpec:
    data = json.loads((FORMS / "nouveau-dossier-client.json").read_text(encoding="utf-8"))
    return FormSpec.model_validate(data)


def _gated_conversation(spec: FormSpec | None = None) -> ConversationState:
    spec = spec or _client_spec()
    return ConversationState(
        space_id="spaces/AAAAtest",
        form_id=spec.form_id,
        contact=Contact(user_email="fdiaz@jin.fr", display_name="Frédéric Diaz"),
        form_spec=spec,
        target_schema=derive_target_schema(spec),
        webhook_url="https://example.test/ingest",
        phase="interlocutor",
        current_field_id=None,
    )


def test_opening_is_intro_then_interlocutor_not_first_field() -> None:
    text = opening_message(_gated_conversation())
    assert "Jin Investigator Agent" in text
    assert "bonne personne" in text or "responsable du dossier" in text
    assert "_sephora" not in text
    assert "SHOW FOLDER" not in text


def test_yes_opens_first_questionnaire_field() -> None:
    result = apply_action(
        _gated_conversation(),
        AgentAction(action="interlocutor_yes", message_to_user="Parfait, on enchaîne."),
    )
    assert result.state.phase == "questionnaire"
    assert result.state.current_field_id == "creation_dossier"
    assert "Parfait" in result.message_to_user
    assert "nouveau dossier client" in result.message_to_user.lower()
    assert not result.abandon


def test_no_asks_for_replacement() -> None:
    result = apply_action(
        _gated_conversation(),
        AgentAction(
            action="interlocutor_no",
            message_to_user="Pas de souci. Peux-tu m'indiquer le prénom, le nom et l'e-mail ?",
        ),
    )
    assert result.state.phase == "awaiting_replacement"
    assert result.state.status == "in_progress"
    assert "e-mail" in result.message_to_user.lower() or "email" in result.message_to_user.lower()


def test_unknown_escalates_and_abandons() -> None:
    result = apply_action(
        _gated_conversation(),
        AgentAction(action="interlocutor_unknown", message_to_user="Merci, j'escale."),
    )
    assert result.abandon
    assert result.escalate_to_email == "fdiaz@jin.fr"
    assert "nouveau-dossier-client-v1" in (result.escalate_message or "")
    assert "fdiaz@jin.fr" in (result.escalate_message or "")


def test_unknown_escalates_to_default_when_if_unknown_missing() -> None:
    spec = _client_spec()
    gate = spec.interlocutor_validation
    assert gate is not None
    spec = spec.model_copy(
        update={"interlocutor_validation": gate.model_copy(update={"if_unknown": None})}
    )
    result = apply_action(
        _gated_conversation(spec),
        AgentAction(action="interlocutor_unknown", message_to_user="Merci."),
    )
    assert result.abandon
    assert result.escalate_to_email == get_settings().default_handoff_contact
    assert result.escalate_message
    assert "nouveau-dossier-client-v1" in result.escalate_message


def test_unknown_escalates_to_default_when_email_not_configured() -> None:
    spec = _client_spec()
    gate = spec.interlocutor_validation
    assert gate is not None and gate.if_unknown is not None
    updated_unknown = gate.if_unknown.model_copy(
        update={"escalate_to_chat_email": "", "escalation_message": ""}
    )
    spec = spec.model_copy(
        update={"interlocutor_validation": gate.model_copy(update={"if_unknown": updated_unknown})}
    )
    result = apply_action(
        _gated_conversation(spec),
        AgentAction(action="interlocutor_unknown", message_to_user="Merci."),
    )
    assert result.escalate_to_email == get_settings().default_handoff_contact
    assert result.escalate_message


def test_replacement_starts_new_conversation() -> None:
    repo = MemoryConversationRepo()
    chat = FakeChatClient()
    spec = _client_spec()
    original = begin_conversation(
        contact=Contact(user_email="alice@jin.fr"),
        form_spec=spec,
        webhook_url="https://example.test/ingest",
        repo=repo,
        chat_client=chat,
    )
    assert original.phase == "interlocutor"
    process_user_message(original.space_id, "non, contacte bob@jin.fr", repo, chat)
    original_after = repo.get(original.space_id)
    assert original_after is not None
    assert original_after.status == "abandoned"
    new_state = repo.get("spaces/fake-bob@jin.fr")
    assert new_state is not None
    assert new_state.phase == "interlocutor"
    assert new_state.contact.user_email == "bob@jin.fr"
    assert any(space == "spaces/fake-bob@jin.fr" for space, _ in chat.messages)


def test_skip_optional_field() -> None:
    spec = _client_spec()
    state = _gated_conversation(spec)
    state.phase = "questionnaire"
    state.current_field_id = "externes"
    state.answers = {
        "creation_dossier": "oui",
        "nom_dossier": "_acme",
        "niveau_securite": "SHOW FOLDER",
        "equipe_jinners": ["marie.martin@jin.fr"],
    }
    result = apply_action(
        state,
        AgentAction(action="skip", field_id="externes", message_to_user="C'est noté."),
    )
    assert "externes" in result.state.skipped_field_ids
    assert result.state.current_field_id == "membres_externes_chat"


def test_creation_non_stops_without_webhook() -> None:
    spec = _client_spec()
    state = _gated_conversation(spec)
    state.phase = "questionnaire"
    state.current_field_id = "creation_dossier"
    result = apply_action(
        state,
        AgentAction(
            action="confirm_value",
            field_id="creation_dossier",
            extracted_value="non",
            message_to_user="C'est noté.",
        ),
    )
    assert result.abandon
    assert not result.webhook_now
    assert result.state.answers["creation_dossier"] == "non"
    assert "ne crée pas" in result.message_to_user
