import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl

from app.core.auth import verify_start_token
from app.core.chat_client import ChatApiError
from app.core.turn import begin_conversation
from app.dependencies import get_chat_client, get_repo
from app.models.form_spec import Contact, FormSpec
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)

router = APIRouter()


class StartRequest(BaseModel):
    form_spec: FormSpec
    webhook_url: HttpUrl
    contact: Contact | None = None
    webhook_secret: str | None = None


class StartResponse(BaseModel):
    space_id: str


def resolve_start_contact(payload: StartRequest) -> Contact:
    recipient = payload.form_spec.recipient
    recipient_user_id = recipient.user_id if recipient else None
    if payload.contact is not None:
        if payload.contact.user_id or not recipient_user_id:
            return payload.contact
        return payload.contact.model_copy(update={"user_id": recipient_user_id})
    if recipient is None or not recipient.email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Indique contact ou form_spec.recipient.email",
        )
    return Contact(
        user_email=recipient.email,
        display_name=recipient.name,
        user_id=recipient.user_id,
    )


@router.post("/start", status_code=status.HTTP_202_ACCEPTED, response_model=StartResponse)
def start_conversation(
    payload: StartRequest,
    request: Request,
    repo: ConversationRepo = Depends(get_repo),
    chat_client=Depends(get_chat_client),
) -> StartResponse:
    verify_start_token(request)
    contact = resolve_start_contact(payload)
    try:
        state = begin_conversation(
            contact=contact,
            form_spec=payload.form_spec,
            webhook_url=str(payload.webhook_url),
            repo=repo,
            chat_client=chat_client,
            webhook_secret=payload.webhook_secret,
        )
    except ChatApiError as exc:
        logger.exception("create_dm_failed", extra={"email": contact.user_email})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from None
    except Exception as exc:
        logger.exception("create_dm_failed", extra={"email": contact.user_email})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Impossible d'ouvrir le DM Google Chat ({type(exc).__name__}: {exc})",
        ) from None
    return StartResponse(space_id=state.space_id)
