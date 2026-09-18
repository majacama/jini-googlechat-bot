from app.core.llm import render_prompt
from app.core.process_registry import ProcessDefinition
from app.models.conversation_state import AgentAction, ConversationState
from app.models.form_spec import FormSpec
from app.models.route import RouteAction


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

    def decide_route(
        self,
        user_message: str | None,
        processes: list[ProcessDefinition],
    ) -> RouteAction:
        del user_message, processes
        raise NotImplementedError(
            "LLM_PROVIDER=anthropic n'est pas implémenté en v1. "
            "Garder la même signature decide_route."
        )
