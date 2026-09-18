from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.config import get_settings
from app.core.text_utils import (
    extract_emails,
    extract_replacement,
    is_affirmative,
    is_negative,
    is_skip_intent,
    is_unknown,
    schema_allows_array,
    schema_const_match,
)
from app.core.process_registry import ProcessDefinition
from app.models.conversation_state import AgentAction, ConversationState, HistoryTurn
from app.models.form_spec import FormSpec
from app.models.route import RouteAction

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.md"
INTERLOCUTOR_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "interlocutor_prompt.md"
)
ROUTER_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "router_prompt.md"


class LLMProvider(Protocol):
    def decide_next_action(
        self,
        form_spec: FormSpec,
        state: ConversationState,
        user_message: str | None,
    ) -> AgentAction: ...

    def decide_route(
        self,
        user_message: str | None,
        processes: list[ProcessDefinition],
    ) -> RouteAction: ...


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_interlocutor_prompt() -> str:
    return INTERLOCUTOR_PROMPT_PATH.read_text(encoding="utf-8")


def load_router_prompt() -> str:
    return ROUTER_PROMPT_PATH.read_text(encoding="utf-8")


def render_router_prompt(user_message: str | None, processes: list[ProcessDefinition]) -> str:
    if processes:
        listing = "\n".join(f"- {proc.process_id} : {proc.trigger_intent}" for proc in processes)
    else:
        listing = "(aucun traitement disponible pour le moment)"
    return load_router_prompt().format(
        processes=listing,
        user_message=user_message or "(vide)",
    )


def render_prompt(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> str:
    if state.phase in {"interlocutor", "awaiting_replacement"}:
        return render_interlocutor_prompt(form_spec, state, user_message)
    field = form_spec.field_by_id(state.current_field_id or "")
    history = "\n".join(_format_turn(turn) for turn in state.recent_history())
    template = load_system_prompt()
    field_ids = ", ".join(item.id for item in form_spec.fields)
    return template.format(
        global_instructions=form_spec.global_instructions,
        language=form_spec.language,
        today=datetime.now(UTC).date().isoformat(),
        field_ids=field_ids,
        field_id=field.id if field else "",
        required=field.required if field else "",
        question_hint=field.question_hint if field else "",
        constraints=field.constraints if field else "",
        format_advice=field.format_advice if field else "",
        examples=field.examples if field else [],
        json_schema=field.json_schema if field else {},
        answers=state.answers,
        history=history or "(vide)",
        user_message=user_message or "(aucun)",
    )


def render_interlocutor_prompt(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> str:
    gate = form_spec.interlocutor_validation
    recipient = form_spec.recipient
    history = "\n".join(_format_turn(turn) for turn in state.recent_history())
    return load_interlocutor_prompt().format(
        global_instructions=form_spec.global_instructions,
        language=form_spec.language,
        form_id=form_spec.form_id,
        recipient_name=(recipient.name if recipient else None) or state.contact.display_name or "",
        recipient_email=(recipient.email if recipient else None) or state.contact.user_email,
        phase=state.phase,
        question=gate.question if gate else "",
        ask_for_replacement=(
            gate.if_no.ask_for_replacement if gate and gate.if_no else ""
        ),
        history=history or "(vide)",
        user_message=user_message or "(aucun)",
    )


def _format_turn(turn: HistoryTurn) -> str:
    return f"- [{turn.ts}] {turn.role} ({turn.field_id or '-'}): {turn.text}"


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        from app.core.llm_anthropic import AnthropicProvider

        return AnthropicProvider()
    if provider == "gemini":
        if not settings.gcp_project:
            return StubProvider()
        from app.core.llm_gemini import GeminiProvider

        return GeminiProvider()
    return StubProvider()


def decide_next_action(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> AgentAction:
    return get_llm_provider().decide_next_action(form_spec, state, user_message)


def decide_route(
    user_message: str | None,
    processes: list[ProcessDefinition],
) -> RouteAction:
    return get_llm_provider().decide_route(user_message, processes)


class StubProvider:
    """Fournisseur déterministe pour les tests unitaires sans appel réseau."""

    def decide_next_action(
        self,
        form_spec: FormSpec,
        state: ConversationState,
        user_message: str | None,
    ) -> AgentAction:
        if state.phase in {"interlocutor", "awaiting_replacement"}:
            return _stub_interlocutor(form_spec, state, user_message)

        field = form_spec.field_by_id(state.current_field_id or "")
        if field is None:
            return AgentAction(
                action="complete",
                field_id=None,
                extracted_value=None,
                message_to_user="Merci, le formulaire est complet.",
            )
        if not user_message:
            return AgentAction(
                action="ask",
                field_id=field.id,
                extracted_value=None,
                message_to_user=field.question_hint,
            )
        if not field.required and is_skip_intent(user_message):
            return AgentAction(
                action="skip",
                field_id=field.id,
                extracted_value=None,
                message_to_user="C'est noté.",
            )
        const = schema_const_match(field.json_schema, user_message)
        if const is not None:
            return AgentAction(
                action="confirm_value",
                field_id=field.id,
                extracted_value=const,
                message_to_user="C'est noté.",
            )
        if schema_allows_array(field.json_schema):
            emails = extract_emails(user_message)
            if emails:
                return AgentAction(
                    action="confirm_value",
                    field_id=field.id,
                    extracted_value=emails,
                    message_to_user="C'est noté.",
                )
        return AgentAction(
            action="confirm_value",
            field_id=field.id,
            extracted_value=user_message.strip(),
            message_to_user="C'est noté.",
        )

    def decide_route(
        self,
        user_message: str | None,
        processes: list[ProcessDefinition],
    ) -> RouteAction:
        text = (user_message or "").strip().lower()
        if not text:
            return RouteAction(
                action="clarify_needed",
                message_to_user="Comment puis-je t'aider ?",
            )
        for proc in processes:
            keywords = [word for word in proc.trigger_intent.lower().split() if len(word) > 4]
            if any(word in text for word in keywords):
                return RouteAction(
                    action="start_process",
                    process_id=proc.process_id,
                    message_to_user="D'accord, on y va.",
                )
        return RouteAction(
            action="search_knowledge_base",
            query=user_message,
            message_to_user="Je cherche ça.",
        )


def _stub_interlocutor(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> AgentAction:
    gate = form_spec.interlocutor_validation
    text = user_message or ""
    name, email = extract_replacement(text)
    if email:
        return AgentAction(
            action="provide_replacement",
            replacement_name=name,
            replacement_email=email,
            message_to_user=f"Merci, je contacte {name or email}.",
        )
    if is_unknown(text) or (state.phase == "awaiting_replacement" and is_skip_intent(text)):
        ack = gate.if_unknown.ack if gate and gate.if_unknown else "Merci, je transmets."
        return AgentAction(action="interlocutor_unknown", message_to_user=ack)
    if state.phase == "interlocutor" and is_affirmative(text):
        ack = gate.if_yes.ack if gate else "Parfait, on enchaîne."
        return AgentAction(action="interlocutor_yes", message_to_user=ack)
    if state.phase == "interlocutor" and is_negative(text):
        ask = (
            gate.if_no.ask_for_replacement
            if gate and gate.if_no
            else "Peux-tu m'indiquer la personne à contacter ?"
        )
        return AgentAction(action="interlocutor_no", message_to_user=ask)
    fallback = gate.question if gate and state.phase == "interlocutor" else (
        gate.if_no.ask_for_replacement if gate and gate.if_no else "Peux-tu préciser ?"
    )
    return AgentAction(action="clarify_needed", message_to_user=fallback)
