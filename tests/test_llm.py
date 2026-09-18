from app.config import get_settings
from app.core.llm import StubProvider, decide_next_action, get_llm_provider, render_prompt
from app.core.llm_gemini import GeminiProvider
from app.models.conversation_state import ConversationState


def test_stub_confirms_raw_user_text(conversation: ConversationState) -> None:
    action = decide_next_action(conversation.form_spec, conversation, "quinze mars")
    assert action.action == "confirm_value"
    assert action.extracted_value == "quinze mars"


def test_prompt_lists_only_spec_fields_and_today(conversation: ConversationState) -> None:
    prompt = render_prompt(conversation.form_spec, conversation, "JIN")
    assert "nom_fournisseur, date_debut, commentaire" in prompt
    assert "Date du jour (UTC)" in prompt
    assert "N'invente aucun champ" in prompt
    assert "action=skip" in prompt


def test_gemini_without_project_falls_back_to_stub(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GCP_PROJECT", "")
    get_settings.cache_clear()
    assert isinstance(get_llm_provider(), StubProvider)


def test_gemini_with_project_selects_gemini_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GCP_PROJECT", "admin-jin-fr")
    get_settings.cache_clear()
    assert isinstance(get_llm_provider(), GeminiProvider)
