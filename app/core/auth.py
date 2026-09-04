import logging

from fastapi import HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)


def verify_start_token(request: Request) -> None:
    settings = get_settings()
    expected = settings.start_endpoint_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="START_ENDPOINT_TOKEN manquant",
        )
    header = request.headers.get("Authorization", "")
    if header != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def verify_chat_request(request: Request) -> None:
    settings = get_settings()
    if settings.chat_auth_disabled and settings.app_env == "dev":
        return

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer")

    token = header.removeprefix("Bearer ").strip()
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        claims = id_token.verify_oauth2_token(token, google_requests.Request())
    except Exception as exc:
        logger.warning("chat_jwt_invalid", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid chat token")

    audience = settings.chat_audience
    if audience and claims.get("aud") != audience:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid audience")
