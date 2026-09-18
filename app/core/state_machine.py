from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.core.text_utils import render_template
from app.core.validation import required_fields_complete, validate_field
from app.models.conversation_state import (
    AgentAction,
    ConversationState,
    HistoryTurn,
    utc_now_iso,
)
from app.models.form_spec import Contact, FieldSpec


@dataclass
class TurnResult:
    state: ConversationState
    message_to_user: str
    completed: bool = False
    webhook_now: bool = False
    abandon: bool = False
    start_replacement: Contact | None = None
    escalate_to_email: str | None = None
    escalate_message: str | None = None


def opening_message(state: ConversationState) -> str:
    intro = state.form_spec.intro_message.strip()
    if state.phase == "interlocutor":
        gate = state.form_spec.interlocutor_validation
        question = (gate.question if gate else "").strip()
        if intro and question:
            return f"{intro}\n\n{question}"
        return intro or question
    field = state.form_spec.field_by_id(state.current_field_id or "")
    question = field.question_hint if field else ""
    if intro and question:
        return f"{intro}\n\n{question}"
    return intro or question


def apply_action(state: ConversationState, action: AgentAction) -> TurnResult:
    state.updated_at = utc_now_iso()

    if state.phase in {"interlocutor", "awaiting_replacement"}:
        return apply_interlocutor(state, action)

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
        return TurnResult(state=state, message_to_user=next_field.question_hint)

    if action.action == "skip":
        if field.required:
            return _append_agent(
                state,
                field,
                action.message_to_user
                or "Ce champ est obligatoire, j'ai besoin d'une valeur.",
            )
        return _skip_optional(state, field)

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


def apply_interlocutor(state: ConversationState, action: AgentAction) -> TurnResult:
    gate = state.form_spec.interlocutor_validation
    if gate is None or not gate.enabled:
        return _enter_questionnaire(state, action.message_to_user)

    if action.action == "provide_replacement" or action.replacement_email:
        email = (action.replacement_email or "").strip()
        if not email and isinstance(action.extracted_value, str) and "@" in action.extracted_value:
            email = action.extracted_value.strip()
        if not email:
            ask = gate.if_no.ask_for_replacement if gate.if_no else "Peux-tu me donner un e-mail ?"
            return _append_agent(state, None, action.message_to_user or ask)
        name = (action.replacement_name or "").strip() or None
        ack = action.message_to_user or f"Merci, je contacte {name or email}."
        record_agent_message(state, ack)
        return TurnResult(
            state=state,
            message_to_user=ack,
            abandon=True,
            start_replacement=Contact(user_email=email, display_name=name),
        )

    if action.action == "interlocutor_yes":
        ack = gate.if_yes.ack if gate.if_yes else "Parfait, on enchaîne."
        return _enter_questionnaire(state, ack)

    if action.action == "interlocutor_no":
        state.phase = "awaiting_replacement"
        ask = (
            gate.if_no.ask_for_replacement
            if gate.if_no
            else "Peux-tu m'indiquer la personne à contacter ?"
        )
        return _append_agent(state, None, action.message_to_user or ask)

    if action.action == "interlocutor_unknown":
        unknown = gate.if_unknown
        ack = unknown.ack if unknown else "Merci, je transmets le sujet."
        record_agent_message(state, ack)
        # Filet de sécurité : un formulaire qui ne configure pas (ou configure
        # incomplètement) if_unknown ne doit jamais aboutir à un abandon
        # silencieux, sans personne notifiée.
        configured_email = unknown.escalate_to_chat_email if unknown else ""
        escalate_email = configured_email or get_settings().default_handoff_contact
        recipient = state.form_spec.recipient
        configured_message = unknown.escalation_message if unknown else ""
        message_template = configured_message or (
            "Formulaire {form_id} : {recipient.email} ({recipient.name}) n'a pas pu "
            "être validé comme interlocuteur et n'a pas indiqué de remplaçant. "
            "Space : {space_id}."
        )
        escalate_message = render_template(
            message_template,
            {
                "form_id": state.form_id,
                "space_id": state.space_id,
                "recipient.email": (recipient.email if recipient else state.contact.user_email),
                "recipient.name": (
                    (recipient.name if recipient else None)
                    or state.contact.display_name
                    or ""
                ),
            },
        )
        return TurnResult(
            state=state,
            message_to_user=ack,
            abandon=True,
            escalate_to_email=escalate_email,
            escalate_message=escalate_message,
        )

    fallback = gate.question if state.phase == "interlocutor" else (
        gate.if_no.ask_for_replacement if gate.if_no else gate.question
    )
    return _append_agent(state, None, action.message_to_user or fallback)


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


def _enter_questionnaire(state: ConversationState, ack: str) -> TurnResult:
    state.phase = "questionnaire"
    first = state.form_spec.fields[0]
    state.current_field_id = first.id
    state.current_attempt_count = 0
    text = f"{ack.strip()}\n\n{first.question_hint}" if ack and ack.strip() else first.question_hint
    return _append_agent(state, first, text)


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
    stop_message = _stop_message(field, value)
    if stop_message is not None:
        record_agent_message(state, stop_message, field.id)
        return TurnResult(state=state, message_to_user=stop_message, abandon=True)

    next_field = state.form_spec.next_pending_field(state.answers, state.skipped_field_ids)
    if next_field is None:
        confirmation = message or "Merci, j'ai tout ce qu'il me faut."
        return _complete(state, confirmation)

    state.current_field_id = next_field.id
    text = f"C'est noté.\n\n{next_field.question_hint}"
    return _append_agent(state, next_field, text)


def _stop_message(field: FieldSpec, value: Any) -> str | None:
    if not field.stop_values:
        return None
    needle = str(value).strip()
    for key, text in field.stop_values.items():
        if key.strip().lower() == needle.lower():
            return text
    return None


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
