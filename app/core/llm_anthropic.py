from app.core.llm import render_prompt
from app.models.conversation_state import AgentAction, ConversationState
from app.models.form_spec import FormSpec


class AnthropicProvider:
    def decide_next_action(
        self,
        form_spec: FormSpec,
        state: ConversationState,
        user_message: str | None,
    ) -> AgentAction:
        del form_spec, state, user_message, render_prompt
        raise NotImplementedError(
            "LLM_PROVIDER=anthropic n'est pas implémenté en v1. "
            "Garder la même signature decide_next_action."
        )
