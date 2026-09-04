import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.core.auth import verify_chat_request
from app.core.turn import process_user_message
from app.dependencies import get_chat_client, get_repo
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat")
async def chat_event(
    request: Request,
    background_tasks: BackgroundTasks,
    repo: ConversationRepo = Depends(get_repo),
    chat_client=Depends(get_chat_client),
) -> dict[str, Any]:
    verify_chat_request(request)
    event = await request.json()
    event_type = event.get("type")
    space = event.get("space") or {}
    space_id = space.get("name")

    if event_type == "MESSAGE" and space_id:
        message = event.get("message") or {}
        sender = message.get("sender") or event.get("user") or {}
        if sender.get("type") == "BOT":
            return {}
        text = (message.get("argumentText") or message.get("text") or "").strip()
        if text:
            background_tasks.add_task(
                process_user_message,
                space_id,
                text,
                repo,
                chat_client,
            )
    elif event_type == "REMOVED_FROM_SPACE" and space_id:
        logger.info("removed_from_space", extra={"space_id": space_id})

    return {}
