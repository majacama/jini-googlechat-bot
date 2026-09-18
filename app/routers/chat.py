import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.auth import verify_chat_request
from app.core.turn import process_user_message
from app.dependencies import get_chat_client, get_repo
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)

router = APIRouter()


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
) -> dict[str, Any]:
    verify_chat_request(request)
    event = await request.json()
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
            )
    elif event_type == "REMOVED_FROM_SPACE" and space_id:
        logger.info("removed_from_space space=%s", space_id)

    return {}
