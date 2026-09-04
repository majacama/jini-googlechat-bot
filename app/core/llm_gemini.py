from app.config import get_settings
from app.core.llm import render_prompt
from app.models.conversation_state import AgentAction, ConversationState
from app.models.form_spec import FormSpec


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
                response_schema=AgentAction,
            ),
        )
        if response.parsed is not None:
            return response.parsed
        return AgentAction.model_validate_json(response.text)
