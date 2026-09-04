from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.auth import verify_start_token
from app.dependencies import get_repo
from app.storage.base import ConversationRepo

router = APIRouter()
_webhook_inbox: list[dict[str, Any]] = []


@router.get("/conversations")
def get_conversation(
    request: Request,
    space_id: str = Query(..., description="Identifiant d'espace Chat, ex. spaces/fake-user@jin.fr"),
    repo: ConversationRepo = Depends(get_repo),
) -> dict[str, Any]:
    verify_start_token(request)
    state = repo.get(space_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation inconnue")
    data = state.model_dump()
    data.pop("webhook_secret", None)
    return data


@router.post("/dev/webhook")
async def catch_webhook(request: Request) -> dict[str, str]:
    payload = await request.json()
    _webhook_inbox.append(
        {
            "headers": {"X-Signature": request.headers.get("X-Signature")},
            "body": payload,
        }
    )
    return {"status": "ok"}


@router.get("/dev/webhook")
def list_webhook_inbox() -> list[dict[str, Any]]:
    return _webhook_inbox
