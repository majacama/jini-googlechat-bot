"""Cartes Google Chat des dossiers clients, construites par le code (jamais par Gemini)."""

from typing import Any

CONFIRM_ACTION = "dossier_confirmer"
MODIFY_ACTION = "dossier_modifier"


def _line(label: str, text: str) -> dict[str, Any]:
    return {"decoratedText": {"topLabel": label, "text": text or "—", "wrapText": True}}


def _emails(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "—"
    return str(value or "—")


def confirmation_card(tool: str, args: dict[str, Any], manager: str) -> dict[str, Any]:
    """Récapitulatif d'une demande, avec « Confirmer » et « Modifier »."""
    if tool == "creer_demande_dossier_client":
        title = "Nouveau dossier client"
        subtitle = f"{args.get('display_name', '')} · {args.get('technical_name', '')}"
        widgets = [
            _line("Nom technique", str(args.get("technical_name", ""))),
            _line("Niveau de sécurité", str(args.get("security_level", 2))),
            _line("Gestionnaire", str(args.get("email_gestionnaire") or manager)),
            _line("Jinners", _emails(args.get("jinners"))),
            _line("Externes", _emails(args.get("externals"))),
        ]
    else:
        title = "Années manquantes"
        subtitle = "Dossier client existant"
        widgets = [
            _line("Dossier client", str(args.get("dossier_url", ""))),
            _line("Gestionnaire", str(args.get("email_gestionnaire") or manager)),
            _line("Jinners ajoutés au groupe", _emails(args.get("jinners"))),
        ]
    widgets.append(
        {
            "buttonList": {
                "buttons": [
                    {"text": "Confirmer", "onClick": {"action": {"function": CONFIRM_ACTION}}},
                    {"text": "Modifier", "onClick": {"action": {"function": MODIFY_ACTION}}},
                ]
            }
        }
    )
    return {
        "cardId": "confirmation-dossier",
        "card": {"header": {"title": title, "subtitle": subtitle}, "sections": [{"widgets": widgets}]},
    }


def answered_card(title: str, status: str) -> dict[str, Any]:
    """Carte remplacée après le clic, pour éviter un second clic."""
    return {
        "cardId": "confirmation-dossier",
        "card": {"header": {"title": title}, "sections": [{"widgets": [{"textParagraph": {"text": status}}]}]},
    }
