import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from app.models.conversation_state import ConversationState

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2, 4)


def sign_body(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def build_payload(state: ConversationState) -> dict[str, Any]:
    return {
        "form_id": state.form_id,
        "space_id": state.space_id,
        "contact": state.contact.model_dump(),
        "answers": state.answers,
        "completed_at": state.completed_at,
    }


def deliver_completion(
    state: ConversationState,
    client: httpx.Client | None = None,
    sleep=time.sleep,
) -> bool:
    payload = build_payload(state)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if state.webhook_secret:
        headers["X-Signature"] = sign_body(body, state.webhook_secret)

    own_client = client is None
    http = client or httpx.Client(timeout=15.0)
    try:
        for attempt, delay in enumerate(BACKOFF_SECONDS, start=1):
            try:
                response = http.post(state.webhook_url, content=body, headers=headers)
                if response.is_success:
                    return True
                logger.error(
                    "webhook_failed",
                    extra={
                        "space_id": state.space_id,
                        "form_id": state.form_id,
                        "attempt": attempt,
                        "status_code": response.status_code,
                    },
                )
            except httpx.HTTPError:
                logger.exception(
                    "webhook_error",
                    extra={
                        "space_id": state.space_id,
                        "form_id": state.form_id,
                        "attempt": attempt,
                    },
                )
            if attempt < MAX_ATTEMPTS:
                sleep(delay)
        return False
    finally:
        if own_client:
            http.close()
