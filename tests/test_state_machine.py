from app.core.state_machine import apply_action, opening_message
from app.models.conversation_state import AgentAction, ConversationState


def test_opening_message_includes_intro_and_first_question(conversation: ConversationState) -> None:
    text = opening_message(conversation)
    assert "fiche fournisseur" in text
    assert "raison sociale" in text


def test_accept_value_moves_to_next_field(conversation: ConversationState) -> None:
    result = apply_action(
        conversation,
        AgentAction(
            action="confirm_value",
            field_id="nom_fournisseur",
            extracted_value="Acme SAS",
            message_to_user="C'est noté.",
        ),
    )
    assert result.state.answers["nom_fournisseur"] == "Acme SAS"
    assert result.state.current_field_id == "date_debut"
    assert not result.completed
    assert "contrat" in result.message_to_user


def test_accept_does_not_forward_llm_extra_questions(conversation: ConversationState) -> None:
    result = apply_action(
        conversation,
        AgentAction(
            action="confirm_value",
            field_id="nom_fournisseur",
            extracted_value="JIN",
            message_to_user=(
                "Quelle est l'adresse email du contact ? Un commentaire à ajouter ?"
            ),
        ),
    )
    assert result.state.answers["nom_fournisseur"] == "JIN"
    assert result.state.current_field_id == "date_debut"
    assert "email" not in result.message_to_user.lower()
    assert "commentaire" not in result.message_to_user.lower()
    assert "contrat" in result.message_to_user


def test_invalid_value_increments_attempts_without_storing(conversation: ConversationState) -> None:
    result = apply_action(
        conversation,
        AgentAction(
            action="confirm_value",
            field_id="nom_fournisseur",
            extracted_value="A",
            message_to_user="Trop court ?",
        ),
    )
    assert "nom_fournisseur" not in result.state.answers
    assert result.state.current_attempt_count == 1
    assert result.state.current_field_id == "nom_fournisseur"
    assert not result.completed


def test_clarify_needed_does_not_increment_attempts(conversation: ConversationState) -> None:
    result = apply_action(
        conversation,
        AgentAction(
            action="clarify_needed",
            field_id="nom_fournisseur",
            extracted_value=None,
            message_to_user="Tu peux préciser la raison sociale ?",
        ),
    )
    assert result.state.current_attempt_count == 0
    assert "préciser" in result.message_to_user


def test_optional_field_skipped_after_max_attempts(conversation: ConversationState) -> None:
    conversation.answers = {
        "nom_fournisseur": "Acme SAS",
        "date_debut": "2026-03-15",
    }
    conversation.current_field_id = "commentaire"
    conversation.current_attempt_count = 1
    result = apply_action(
        conversation,
        AgentAction(
            action="confirm_value",
            field_id="commentaire",
            extracted_value="x",
            message_to_user="",
        ),
    )
    assert "commentaire" not in result.state.answers
    assert "commentaire" in result.state.skipped_field_ids
    assert result.completed
    assert result.webhook_now


def test_required_field_stays_after_max_attempts(conversation: ConversationState) -> None:
    conversation.current_attempt_count = 2
    result = apply_action(
        conversation,
        AgentAction(
            action="confirm_value",
            field_id="nom_fournisseur",
            extracted_value="A",
            message_to_user="",
        ),
    )
    assert not result.completed
    assert result.state.status == "in_progress"
    assert result.state.current_field_id == "nom_fournisseur"
    assert result.state.current_attempt_count == 3
    assert "collègue" in result.message_to_user or "valider" in result.message_to_user


def test_complete_only_when_required_filled(conversation: ConversationState) -> None:
    result = apply_action(
        conversation,
        AgentAction(
            action="complete",
            field_id=None,
            extracted_value=None,
            message_to_user="Terminé !",
        ),
    )
    assert not result.completed
    assert result.state.current_field_id == "nom_fournisseur"


def test_accept_moves_to_optional_field(conversation: ConversationState) -> None:
    conversation.answers = {"nom_fournisseur": "Acme SAS"}
    conversation.current_field_id = "date_debut"
    result = apply_action(
        conversation,
        AgentAction(
            action="confirm_value",
            field_id="date_debut",
            extracted_value="2026-03-15",
            message_to_user="Parfait.",
        ),
    )
    assert result.state.answers["date_debut"] == "2026-03-15"
    assert result.state.current_field_id == "commentaire"
    assert not result.completed
