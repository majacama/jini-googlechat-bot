import logging

from fastapi import HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)

CHAT_ISSUER = "chat@system.gserviceaccount.com"
CHAT_CERTS_URL = (
    "https://www.googleapis.com/service_accounts/v1/metadata/x509/" + CHAT_ISSUER
)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer"
        )

    token = header.removeprefix("Bearer ").strip()
    try:
        claims = verify_chat_jwt(token)
    except Exception as exc:
        logger.warning("chat_jwt_invalid", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid chat token"
        ) from None

    email = claims.get("email")
    issuer = claims.get("iss")
    if email != CHAT_ISSUER and issuer != CHAT_ISSUER:
        logger.warning("chat_jwt_wrong_issuer", extra={"iss": issuer, "email": email})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid chat issuer"
        )


def verify_chat_jwt(token: str) -> dict:
    """Vérifie le Bearer Google Chat (audience URL ou numéro de projet)."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    settings = get_settings()
    request = google_requests.Request()
    errors: list[str] = []

    if settings.chat_audience:
        try:
            claims = id_token.verify_oauth2_token(
                token, request, audience=settings.chat_audience
            )
            if claims.get("email") == CHAT_ISSUER:
                return dict(claims)
            errors.append("OIDC: email n'est pas chat@system.gserviceaccount.com")
        except Exception as exc:
            errors.append(f"OIDC URL: {exc}")
        try:
            claims = id_token.verify_token(
                token,
                request,
                audience=settings.chat_audience,
                certs_url=CHAT_CERTS_URL,
            )
            if claims.get("iss") == CHAT_ISSUER or claims.get("email") == CHAT_ISSUER:
                return dict(claims)
            errors.append("certs URL: issuer Chat absent")
        except Exception as exc:
            errors.append(f"certs URL: {exc}")

    if settings.google_chat_app_id:
        try:
            claims = id_token.verify_token(
                token,
                request,
                audience=settings.google_chat_app_id,
                certs_url=CHAT_CERTS_URL,
            )
            if claims.get("iss") == CHAT_ISSUER:
                return dict(claims)
            errors.append("project number: issuer Chat absent")
        except Exception as exc:
            errors.append(f"project number: {exc}")

    if not settings.chat_audience and not settings.google_chat_app_id:
        raise RuntimeError("CHAT_AUDIENCE ou GOOGLE_CHAT_APP_ID manquant")
    raise ValueError(" ; ".join(errors) or "JWT Chat invalide")
