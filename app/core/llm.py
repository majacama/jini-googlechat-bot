from pathlib import Path
from typing import Protocol

from app.config import get_settings
from app.models.conversation_state import AgentAction, ConversationState, HistoryTurn
from app.models.form_spec import FormSpec

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.md"


class LLMProvider(Protocol):
    def decide_next_action(
        self,
        form_spec: FormSpec,
        state: ConversationState,
        user_message: str | None,
    ) -> AgentAction: ...


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_prompt(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> str:
    field = form_spec.field_by_id(state.current_field_id or "")
    history = "\n".join(_format_turn(turn) for turn in state.recent_history())
    template = load_system_prompt()
    return template.format(
        global_instructions=form_spec.global_instructions,
        language=form_spec.language,
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


def _format_turn(turn: HistoryTurn) -> str:
    return f"- [{turn.ts}] {turn.role} ({turn.field_id or '-'}): {turn.text}"


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        from app.core.llm_anthropic import AnthropicProvider

        return AnthropicProvider()
    local_without_gcp = settings.use_memory_store or (
        settings.app_env == "dev" and not settings.gcp_project
    )
    if provider == "stub" or (provider == "gemini" and local_without_gcp):
        return StubProvider()
    from app.core.llm_gemini import GeminiProvider

    return GeminiProvider()


def decide_next_action(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> AgentAction:
    return get_llm_provider().decide_next_action(form_spec, state, user_message)


class StubProvider:
    """Fournisseur déterministe pour les tests unitaires sans appel réseau."""

    def decide_next_action(
        self,
        form_spec: FormSpec,
        state: ConversationState,
        user_message: str | None,
    ) -> AgentAction:
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
        return AgentAction(
            action="confirm_value",
            field_id=field.id,
            extracted_value=user_message.strip(),
            message_to_user="C'est noté.",
        )
