import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.auth import verify_scheduler_request
from app.dependencies import get_chat_client
from app.dossiers.feed import deliver_feed

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/tasks/bot-feed")
async def bot_feed(request: Request, chat_client=Depends(get_chat_client)) -> dict[str, Any]:
    """Appelé par Cloud Scheduler : livre le fil de travail admin.jin.fr (spec §11)."""
    verify_scheduler_request(request)
    return await asyncio.to_thread(deliver_feed, chat_client)
