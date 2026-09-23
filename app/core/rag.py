"""Cartes Google Chat (CardsV2) pour les sources d'une réponse de la base de connaissances (cas A)."""

from typing import Any

from app.kb.types import KbHit


def _excerpt(content: str, limit: int = 300) -> str:
    text = " ".join(content.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def build_rag_cards(sources: list[KbHit]) -> list[dict[str, Any]]:
    """Une carte par document source : extrait le plus pertinent + bouton vers Drive."""
    cards: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        widgets: list[dict[str, Any]] = []
        if _excerpt(source.content):
            widgets.append({"textParagraph": {"text": _excerpt(source.content)}})
        if source.link:
            widgets.append(
                {
                    "buttonList": {
                        "buttons": [
                            {
                                "text": "Ouvrir dans Drive",
                                "onClick": {"openLink": {"url": source.link}},
                            }
                        ]
                    }
                }
            )
        cards.append(
            {
                "cardId": f"rag-result-{index}",
                "card": {
                    "header": {"title": source.name},
                    "sections": [{"widgets": widgets}] if widgets else [],
                },
            }
        )
    return cards
