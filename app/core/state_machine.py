from dataclasses import dataclass
from typing import Any

from app.core.validation import required_fields_complete, validate_field
from app.models.conversation_state import (
    AgentAction,
    ConversationState,
    HistoryTurn,
    utc_now_iso,
)
from app.models.form_spec import FieldSpec


@dataclass
class TurnResult:
    state: ConversationState
    message_to_user: str
    completed: bool = False
    webhook_now: bool = False


def opening_message(state: ConversationState) -> str:
    field = state.form_spec.field_by_id(state.current_field_id or "")
    question = field.question_hint if field else ""
    intro = state.form_spec.intro_message.strip()
    if intro and question:
        return f"{intro}\n\n{question}"
    return intro or question


def apply_action(state: ConversationState, action: AgentAction) -> TurnResult:
    state.updated_at = utc_now_iso()

    if action.action == "complete" and required_fields_complete(state.form_spec, state.answers):
        return _complete(state, action.message_to_user)

    field = _resolve_field(state, action)
    if field is None:
        next_field = state.form_spec.next_pending_field(state.answers, state.skipped_field_ids)
        if next_field is None:
            if required_fields_complete(state.form_spec, state.answers):
                return _complete(state, action.message_to_user)
            return TurnResult(
                state=state,
                message_to_user=action.message_to_user
                or "Je n'ai plus de champ à traiter. Peux-tu reformuler ?",
            )
        state.current_field_id = next_field.id
        state.current_attempt_count = 0
        return TurnResult(state=state, message_to_user=_ask_message(next_field, action))

    if action.extracted_value is not None and action.action in {
        "confirm_value",
        "ask",
        "reformulate",
        "complete",
    }:
        return _try_accept(state, field, action)

    if action.action == "clarify_needed":
        return _append_agent(state, field, action.message_to_user)

    return _append_agent(state, field, action.message_to_user or field.question_hint)


def record_user_message(state: ConversationState, text: str) -> ConversationState:
    state.history.append(
        HistoryTurn(role="user", field_id=state.current_field_id, text=text)
    )
    state.updated_at = utc_now_iso()
    return state


def record_agent_message(
    state: ConversationState, text: str, field_id: str | None = None
) -> ConversationState:
    state.history.append(
        HistoryTurn(role="agent", field_id=field_id or state.current_field_id, text=text)
    )
    state.updated_at = utc_now_iso()
    return state


def _try_accept(state: ConversationState, field: FieldSpec, action: AgentAction) -> TurnResult:
    result = validate_field(field, action.extracted_value)
    if result.ok:
        return _accept_value(state, field, result.value, action.message_to_user)

    state.current_attempt_count += 1
    if state.current_attempt_count >= field.max_attempts:
        if not field.required:
            return _skip_optional(state, field)
        message = (
            action.message_to_user
            or f"Je n'arrive pas à valider « {field.id} » après plusieurs essais. "
            "Peux-tu fournir une valeur au format attendu, ou demander à un collègue de reprendre ?"
        )
        if result.error:
            message = f"{message}\n({result.error})"
        return _append_agent(state, field, message)

    reformulation = action.message_to_user
    if not reformulation or action.action == "confirm_value":
        reformulation = _default_reformulation(field, result.error)
    return _append_agent(state, field, reformulation)


def _accept_value(
    state: ConversationState, field: FieldSpec, value: Any, message: str
) -> TurnResult:
    state.answers[field.id] = value
    state.current_attempt_count = 0
    next_field = state.form_spec.next_pending_field(state.answers, state.skipped_field_ids)
    if next_field is None:
        confirmation = message or "Merci, j'ai tout ce qu'il me faut."
        return _complete(state, confirmation)

    state.current_field_id = next_field.id
    follow_up = message.strip() if message else ""
    question = next_field.question_hint
    text = f"{follow_up}\n\n{question}".strip() if follow_up else question
    return _append_agent(state, next_field, text)


def _skip_optional(state: ConversationState, field: FieldSpec) -> TurnResult:
    if field.id not in state.skipped_field_ids:
        state.skipped_field_ids.append(field.id)
    state.current_attempt_count = 0
    next_field = state.form_spec.next_pending_field(state.answers, state.skipped_field_ids)
    skip_msg = f"On laisse de côté « {field.id} » pour le moment."
    if next_field is None:
        if required_fields_complete(state.form_spec, state.answers):
            return _complete(state, f"{skip_msg} Merci, le formulaire est complet.")
        return _append_agent(state, field, skip_msg)

    state.current_field_id = next_field.id
    return _append_agent(state, next_field, f"{skip_msg}\n\n{next_field.question_hint}")


def _complete(state: ConversationState, message: str) -> TurnResult:
    state.status = "in_progress"
    state.current_field_id = None
    state.completed_at = utc_now_iso()
    record_agent_message(state, message)
    return TurnResult(state=state, message_to_user=message, completed=True, webhook_now=True)


def _append_agent(state: ConversationState, field: FieldSpec | None, message: str) -> TurnResult:
    record_agent_message(state, message, field.id if field else None)
    return TurnResult(state=state, message_to_user=message)


def _resolve_field(state: ConversationState, action: AgentAction) -> FieldSpec | None:
    field_id = action.field_id or state.current_field_id
    if not field_id:
        return None
    return state.form_spec.field_by_id(field_id)


def _ask_message(field: FieldSpec, action: AgentAction) -> str:
    return action.message_to_user or field.question_hint


def _default_reformulation(field: FieldSpec, error: str | None) -> str:
    parts = [
        "Je n'ai pas pu enregistrer cette réponse telle quelle.",
        field.format_advice or field.constraints,
    ]
    if field.examples:
        parts.append(f"Exemple attendu : {field.examples[0]}")
    if error:
        parts.append(f"Détail : {error}")
    parts.append(field.question_hint)
    return " ".join(part for part in parts if part)
