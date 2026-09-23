from app.core.rag import build_rag_cards
from app.kb.types import KbHit


def _hit(name="Doc A", link="https://drive.google.com/x", content="Extrait A", file_id="a") -> KbHit:
    return KbHit(file_id, name, link, 0, content, 0.8)


def test_build_rag_cards_includes_excerpt_and_drive_button() -> None:
    cards = build_rag_cards([_hit()])
    assert len(cards) == 1
    card = cards[0]["card"]
    assert card["header"]["title"] == "Doc A"
    widgets = card["sections"][0]["widgets"]
    assert {"textParagraph": {"text": "Extrait A"}} in widgets
    button = widgets[-1]["buttonList"]["buttons"][0]
    assert button["onClick"]["openLink"]["url"] == "https://drive.google.com/x"


def test_build_rag_cards_without_link_has_no_button() -> None:
    widgets = build_rag_cards([_hit(link="")])[0]["card"]["sections"][0]["widgets"]
    assert all("buttonList" not in w for w in widgets)


def test_build_rag_cards_truncates_long_excerpt() -> None:
    text = build_rag_cards([_hit(content="mot " * 200)])[0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert len(text) <= 301 and text.endswith("…")


def test_build_rag_cards_multiple_sources_get_distinct_ids() -> None:
    cards = build_rag_cards([_hit(file_id="a"), _hit(file_id="b")])
    assert [c["cardId"] for c in cards] == ["rag-result-0", "rag-result-1"]
