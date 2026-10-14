"""Point d'entrée des dossiers clients dans le bot : messages et clics sur les cartes."""

import logging
from typing import Any

from app.core.chat_client import resolve_sender_email
from app.dossiers.agent import DossierLLM, TurnResult, confirm_pending, modify_pending, run_turn
from app.dossiers.cards import CONFIRM_ACTION, MODIFY_ACTION, answered_card
from app.dossiers.mcp_client import AdminMcpClient
from app.dossiers.session import DossierSession

logger = logging.getLogger(__name__)


def _send(space_id: str, result: TurnResult, chat_client) -> None:
    for reply in result.replies:
        chat_client.send_message(space_id, reply.text or "", cards=reply.cards)


def start_dossier(
    space_id: str,
    sender: dict[str, Any],
    text: str,
    chat_client,
    store,
    llm: DossierLLM | None = None,
    mcp: AdminMcpClient | None = None,
) -> None:
    """Mode 1 : la personne qui écrit au bot demande un dossier client."""
    email = resolve_sender_email(sender)
    if not email:
        chat_client.send_message(space_id, "Je n'arrive pas à retrouver ton adresse e-mail. Réessaie plus tard.")
        return
    session = DossierSession(space_id=space_id, user_email=email.lower())
    result = run_turn(session, text, llm=llm, mcp=mcp)
    store.save(session)
    _send(space_id, result, chat_client)


def continue_dossier(session: DossierSession, text: str, chat_client, store, llm=None, mcp=None) -> None:
    if text.strip().lower() in {"annuler", "stop", "abandonner"}:
        session.active = False
        session.pending = None
        store.save(session)
        chat_client.send_message(session.space_id, "D'accord, j'arrête là. Rien n'a été demandé.")
        return
    result = run_turn(session, text, llm=llm, mcp=mcp)
    store.save(session)
    _send(session.space_id, result, chat_client)


def handle_card_click(
    space_id: str,
    sender: dict[str, Any],
    function: str,
    chat_client,
    store,
    llm=None,
    mcp=None,
) -> dict[str, Any] | None:
    """Clic sur une carte de confirmation. Renvoie la réponse Chat qui remplace la carte."""
    if function not in {CONFIRM_ACTION, MODIFY_ACTION}:
        return None
    session = store.get(space_id)
    email = (resolve_sender_email(sender) or "").lower()
    if session is None or session.pending is None:
        return {"actionResponse": {"type": "UPDATE_MESSAGE"}, "cardsV2": [answered_card("Demande", "Cette demande n'est plus en attente.")]}
    if email != session.user_email:
        chat_client.send_message(space_id, "Seule la personne qui fait la demande peut la confirmer.")
        return None

    if function == CONFIRM_ACTION:
        result = confirm_pending(session, mcp=mcp)
        store.save(session)
        _send(space_id, result, chat_client)
        return {"actionResponse": {"type": "UPDATE_MESSAGE"}, "cardsV2": [answered_card("Demande", "Confirmée.")]}

    result = modify_pending(session, llm=llm, mcp=mcp)
    store.save(session)
    _send(space_id, result, chat_client)
    return {"actionResponse": {"type": "UPDATE_MESSAGE"}, "cardsV2": [answered_card("Demande", "À modifier : on reprend.")]}
