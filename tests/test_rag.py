import pytest

from app.config import get_settings
from app.core import rag as rag_module
from app.core.rag import RagPassage, _clean_text, build_rag_cards, search_corpus


@pytest.fixture(autouse=True)
def _configure_discovery_engine(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DISCOVERY_ENGINE_ID", "jin-knowledge-search_test")
    yield
    get_settings.cache_clear()


def test_search_corpus_without_engine_configured_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCOVERY_ENGINE_ID", "")
    get_settings.cache_clear()
    assert search_corpus("question", user_email="fdiaz@jin.fr") == []


def test_search_corpus_without_user_email_never_calls_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(user_email: str) -> str:
        raise AssertionError("ne doit jamais etre appele sans user_email")

    monkeypatch.setattr(rag_module, "_delegated_access_token", _boom)
    assert search_corpus("question", user_email=None) == []


def test_search_corpus_delegation_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rag_module,
        "_delegated_access_token",
        lambda user_email: (_ for _ in ()).throw(RuntimeError("signJwt a échoué (403)")),
    )
    assert search_corpus("question", user_email="marie.martin@jin.fr") == []


def test_clean_text_strips_html_entity_escaped_tags() -> None:
    assert _clean_text("Budget &lt;b&gt;JIN&lt;/b&gt; 2026") == "Budget JIN 2026"


def test_clean_text_strips_unicode_escaped_tags() -> None:
    # json.loads a deja transforme <b> en <b> avant d'arriver ici.
    assert _clean_text("Contrat <b>Sephora</b> signe") == "Contrat Sephora signe"


def test_clean_text_handles_empty() -> None:
    assert _clean_text("") == ""
    assert _clean_text(None) == ""  # type: ignore[arg-type]


def test_build_rag_cards_includes_snippet_and_drive_button() -> None:
    passages = [RagPassage(title="Doc A", link="https://drive.google.com/x", snippet="Extrait A")]
    cards = build_rag_cards(passages)
    assert len(cards) == 1
    card = cards[0]["card"]
    assert card["header"]["title"] == "Doc A"
    widgets = card["sections"][0]["widgets"]
    assert {"textParagraph": {"text": "Extrait A"}} in widgets
    button = widgets[-1]["buttonList"]["buttons"][0]
    assert button["onClick"]["openLink"]["url"] == "https://drive.google.com/x"


def test_build_rag_cards_without_link_has_no_button() -> None:
    passages = [RagPassage(title="Doc B", link="", snippet="Extrait B")]
    cards = build_rag_cards(passages)
    widgets = cards[0]["card"]["sections"][0]["widgets"]
    assert all("buttonList" not in w for w in widgets)


def test_build_rag_cards_multiple_passages_get_distinct_ids() -> None:
    passages = [
        RagPassage(title="A", link="", snippet="a"),
        RagPassage(title="B", link="", snippet="b"),
    ]
    cards = build_rag_cards(passages)
    assert [c["cardId"] for c in cards] == ["rag-result-0", "rag-result-1"]
