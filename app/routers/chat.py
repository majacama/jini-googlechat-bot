import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.auth import verify_chat_request
from app.core.turn import process_user_message
from app.dependencies import get_chat_client, get_dossier_store, get_repo
from app.core.chat_client import resolve_sender_email
from app.dossiers.feed import REFUSE_ACTION, VALIDATE_ACTION, handle_decision_click
from app.dossiers.handlers import handle_card_click
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)

router = APIRouter()


def parse_card_click(event: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any], dict[str, str]]:
    """Clic sur un bouton de carte : (fonction, space_id, sender, paramètres), formats Chat et add-on."""
    common = event.get("common") or event.get("commonEventObject") or {}
    action = event.get("action") or {}
    function = common.get("invokedFunction") or action.get("actionMethodName")
    params = dict(common.get("parameters") or {})
    params.update({p["key"]: p.get("value") for p in action.get("parameters") or [] if "key" in p})
    payload = (event.get("chat") or {}).get("buttonClickedPayload") or {}
    space = payload.get("space") or event.get("space") or {}
    sender = payload.get("user") or event.get("user") or {}
    return function, space.get("name"), sender, params


def parse_chat_event(event: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any]]:
    """Extrait type, space_id et message (format Chat classique ou add-on)."""
    payload = (event.get("chat") or {}).get("messagePayload") or {}
    if payload:
        space = payload.get("space") or {}
        return "MESSAGE", space.get("name"), payload.get("message") or {}
    space = event.get("space") or {}
    return event.get("type"), space.get("name"), event.get("message") or {}


@router.post("/chat")
async def chat_event(
    request: Request,
    repo: ConversationRepo = Depends(get_repo),
    chat_client=Depends(get_chat_client),
    dossier_store=Depends(get_dossier_store),
) -> dict[str, Any]:
    verify_chat_request(request)
    event = await request.json()

    if event.get("type") == "CARD_CLICKED" or (event.get("chat") or {}).get("buttonClickedPayload"):
        function, space_id, sender, params = parse_card_click(event)
        logger.info("card_clicked function=%s space=%s", function, space_id)
        if function in {VALIDATE_ACTION, REFUSE_ACTION} and space_id:
            email = await asyncio.to_thread(resolve_sender_email, sender)
            response = await asyncio.to_thread(handle_decision_click, email, function, params, chat_client, space_id)
            return response or {}
        if function and space_id:
            response = await asyncio.to_thread(handle_card_click, space_id, sender, function, chat_client, dossier_store)
            return response or {}
        return {}
    event_type, space_id, message = parse_chat_event(event)
    sender = message.get("sender") or event.get("user") or {}
    text = (message.get("argumentText") or message.get("text") or "").strip()

    logger.info(
        "chat_event type=%s space=%s sender=%s text_len=%s keys=%s",
        event_type,
        space_id,
        sender.get("type"),
        len(text),
        list(event.keys()),
    )

    if event_type == "MESSAGE" and space_id:
        if sender.get("type") == "BOT":
            return {}
        if text:
            # Traiter avant l'accusé : Cloud Run gèle le CPU dès la réponse HTTP.
            await asyncio.to_thread(
                process_user_message,
                space_id,
                text,
                repo,
                chat_client,
                sender,
                dossier_store,
            )
    elif event_type == "REMOVED_FROM_SPACE" and space_id:
        logger.info("removed_from_space space=%s", space_id)

    return {}
