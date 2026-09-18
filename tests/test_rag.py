from app.core.rag import RagPassage, _clean_text, build_rag_cards


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
