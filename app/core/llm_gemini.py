import logging

from app.config import get_settings
from app.core.llm import render_prompt, render_router_prompt
from app.core.process_registry import ProcessDefinition
from app.models.conversation_state import AgentAction, ConversationState
from app.models.form_spec import FormSpec
from app.models.route import RouteAction

logger = logging.getLogger(__name__)

_ROUTE_ACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {
            "type": "STRING",
            "enum": ["search_knowledge_base", "start_process", "clarify_needed"],
        },
        "process_id": {"type": "STRING", "nullable": True},
        "query": {"type": "STRING", "nullable": True},
        "message_to_user": {"type": "STRING"},
    },
    "required": ["action", "message_to_user"],
}

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

    def decide_route(
        self,
        user_message: str | None,
        processes: list[ProcessDefinition],
        recent: list[dict] | None = None,
    ) -> RouteAction:
        from google import genai
        from google.genai import types

        settings = get_settings()
        client = genai.Client(
            vertexai=True,
            project=settings.gcp_project or None,
            location=settings.gcp_region,
        )
        schema = dict(_ROUTE_ACTION_SCHEMA)
        schema["properties"] = dict(schema["properties"])
        process_ids = [proc.process_id for proc in processes]
        if process_ids:
            schema["properties"]["process_id"] = {
                "type": "STRING",
                "nullable": True,
                "enum": process_ids,
            }
        prompt = render_router_prompt(user_message, processes, recent)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                thinking_config=types.ThinkingConfig(thinking_budget=128),
            ),
        )
        if response.parsed is not None:
            if isinstance(response.parsed, RouteAction):
                return response.parsed
            return RouteAction.model_validate(response.parsed)
        if response.text:
            return RouteAction.model_validate_json(response.text)
        logger.warning("gemini_empty_route_response")
        return RouteAction(
            action="clarify_needed",
            message_to_user="Je n'ai pas bien compris, peux-tu reformuler ?",
        )
