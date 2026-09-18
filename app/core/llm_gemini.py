import logging

from app.config import get_settings
from app.core.llm import render_prompt
from app.models.conversation_state import AgentAction, ConversationState
from app.models.form_spec import FormSpec

logger = logging.getLogger(__name__)

_AGENT_ACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {
            "type": "STRING",
            "enum": [
                "ask",
                "confirm_value",
                "reformulate",
                "complete",
                "clarify_needed",
                "skip",
                "interlocutor_yes",
                "interlocutor_no",
                "interlocutor_unknown",
                "provide_replacement",
            ],
        },
        "field_id": {"type": "STRING", "nullable": True},
        "extracted_value": {
            "nullable": True,
            "anyOf": [
                {"type": "STRING"},
                {"type": "NUMBER"},
                {"type": "INTEGER"},
                {"type": "BOOLEAN"},
                {"type": "ARRAY", "items": {"type": "STRING"}},
            ],
        },
        "replacement_name": {"type": "STRING", "nullable": True},
        "replacement_email": {"type": "STRING", "nullable": True},
        "message_to_user": {"type": "STRING"},
    },
    "required": ["action", "message_to_user"],
}


class GeminiProvider:
    def decide_next_action(
        self,
        form_spec: FormSpec,
        state: ConversationState,
        user_message: str | None,
    ) -> AgentAction:
        from google import genai
        from google.genai import types

        settings = get_settings()
        client = genai.Client(
            vertexai=True,
            project=settings.gcp_project or None,
            location=settings.gcp_region,
        )
        prompt = render_prompt(form_spec, state, user_message)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_AGENT_ACTION_SCHEMA,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
                thinking_config=types.ThinkingConfig(thinking_budget=128),
            ),
        )
        if response.parsed is not None:
            if isinstance(response.parsed, AgentAction):
                return response.parsed
            return AgentAction.model_validate(response.parsed)
        if response.text:
            return AgentAction.model_validate_json(response.text)
        logger.warning("gemini_empty_response", extra={"field_id": state.current_field_id})
        return AgentAction(
            action="clarify_needed",
            field_id=state.current_field_id,
            extracted_value=None,
            message_to_user="Je n'ai pas bien compris, peux-tu reformuler ?",
        )
