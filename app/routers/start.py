import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl

from app.core.auth import verify_start_token
from app.core.chat_client import ChatApiError
from app.core.turn import send_opening
from app.dependencies import get_chat_client, get_repo
from app.models.conversation_state import ConversationState
from app.models.form_spec import Contact, FormSpec, derive_target_schema
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)

router = APIRouter()


class StartRequest(BaseModel):
    contact: Contact
    form_spec: FormSpec
    webhook_url: HttpUrl
    webhook_secret: str | None = None


class StartResponse(BaseModel):
    space_id: str


@router.post("/start", status_code=status.HTTP_202_ACCEPTED, response_model=StartResponse)
def start_conversation(
    payload: StartRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    repo: ConversationRepo = Depends(get_repo),
    chat_client=Depends(get_chat_client),
) -> StartResponse:
    verify_start_token(request)
    try:
        space_id = chat_client.create_dm(
            payload.contact.user_id or payload.contact.user_email
        )
    except ChatApiError as exc:
        logger.exception("create_dm_failed", extra={"email": payload.contact.user_email})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from None
    except Exception:
        logger.exception("create_dm_failed", extra={"email": payload.contact.user_email})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Impossible d'ouvrir le DM Google Chat",
        ) from None

    first_field = payload.form_spec.fields[0]
    state = ConversationState(
        space_id=space_id,
        form_id=payload.form_spec.form_id,
        contact=payload.contact,
        form_spec=payload.form_spec,
        target_schema=derive_target_schema(payload.form_spec),
        webhook_url=str(payload.webhook_url),
        webhook_secret=payload.webhook_secret,
        current_field_id=first_field.id,
    )
    repo.save(state)
    background_tasks.add_task(send_opening, state, repo, chat_client)
    logger.info(
        "conversation_started",
        extra={"space_id": space_id, "form_id": state.form_id, "field_id": first_field.id},
    )
    return StartResponse(space_id=space_id)
