import logging
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

CHAT_API = "https://chat.googleapis.com/v1"
CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
DIRECTORY_API = "https://admin.googleapis.com/admin/directory/v1"
DIRECTORY_SCOPE = "https://www.googleapis.com/auth/admin.directory.user.readonly"


class ChatApiError(RuntimeError):
    def __init__(self, action: str, status_code: int, body: str) -> None:
        self.action = action
        self.status_code = status_code
        self.body = body
        super().__init__(f"Google Chat {action} a échoué (HTTP {status_code}): {body}")


class ChatClient(Protocol):
    def create_dm(self, user_email: str) -> str: ...

    def send_message(self, space_id: str, text: str) -> None: ...


class GoogleChatClient:
    def __init__(self, access_token: str | None = None) -> None:
        self._access_token = access_token

    def _headers(self) -> dict[str, str]:
        token = self._access_token or _chat_app_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def create_dm(self, user_email: str) -> str:
        # En auth app, Chat refuse users/email@domaine (alias). Il faut users/{id}.
        user_name = (
            _user_resource_name(user_email)
            if self._access_token
            else resolve_chat_user_name(user_email)
        )
        if "@" not in user_name:
            existing = self._get(
                f"{CHAT_API}/spaces:findDirectMessage",
                params={"name": user_name},
                action="spaces.findDirectMessage",
            )
            if existing and existing.get("name"):
                return existing["name"]

        raise ChatApiError(
            "spaces.findDirectMessage",
            404,
            "Aucun DM app ↔ utilisateur. chat.bot ne permet pas de CRÉER ce DM "
            "(spaces.setup exige d'autres scopes). Dans Google Chat, installe "
            "« Agent formulaire », envoie-lui un message, puis relance le test.",
        )

    def send_message(self, space_id: str, text: str) -> None:
        self._post(
            f"{CHAT_API}/{space_id}/messages",
            {"text": text},
            action="spaces.messages.create",
        )

    def _get(self, url: str, params: dict[str, str], action: str) -> dict[str, Any] | None:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, headers=self._headers(), params=params)
        if response.status_code == 404:
            return None
        if response.is_error:
            raise ChatApiError(action, response.status_code, response.text)
        return response.json()

    def _post(self, url: str, payload: dict[str, Any], action: str) -> dict[str, Any]:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(url, headers=self._headers(), json=payload)
        if response.is_error:
            raise ChatApiError(action, response.status_code, response.text)
        return response.json()


class FakeChatClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.dms: list[str] = []

    def create_dm(self, user_email: str) -> str:
        space_id = f"spaces/fake-{user_email}"
        self.dms.append(space_id)
        return space_id

    def send_message(self, space_id: str, text: str) -> None:
        self.messages.append((space_id, text))
        logger.info("fake_chat_send", extra={"space_id": space_id, "text": text})


def _user_resource_name(identifier: str) -> str:
    raw = identifier.removeprefix("users/")
    return raw if raw.startswith("users/") else f"users/{raw}"


def resolve_chat_user_name(identifier: str) -> str:
    raw = identifier.removeprefix("users/")
    if "@" not in raw:
        return f"users/{raw}"

    self_id = _numeric_id_if_self(raw)
    if self_id:
        return f"users/{self_id}"

    directory_id = _directory_user_id(raw)
    if directory_id:
        return f"users/{directory_id}"

    logger.warning(
        "chat_user_id_unresolved",
        extra={"email": raw},
    )
    return f"users/{raw}"


def _numeric_id_if_self(email: str) -> str | None:
    """OAuth userinfo : l'id numérique = users/{id} Chat, sans Directory API."""
    try:
        token = _user_cloud_token()
        response = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        if not response.is_success:
            return None
        data = response.json()
        if (data.get("email") or "").lower() == email.lower() and data.get("id"):
            return str(data["id"])
    except Exception:
        logger.debug("userinfo_lookup_failed", exc_info=True)
    return None


def _directory_user_id(email: str) -> str | None:
    try:
        token = _directory_token()
        response = httpx.get(
            f"{DIRECTORY_API}/users/{email}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        if not response.is_success:
            logger.debug(
                "directory_lookup_http",
                extra={"email": email, "status": response.status_code},
            )
            return None
        user_id = response.json().get("id")
        return str(user_id) if user_id else None
    except Exception:
        logger.debug("directory_lookup_failed", extra={"email": email}, exc_info=True)
        return None


def _directory_token() -> str:
    import google.auth
    import google.auth.impersonated_credentials
    import google.auth.transport.requests

    from app.config import get_settings

    settings = get_settings()
    request = google.auth.transport.requests.Request()
    source, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if getattr(source, "requires_scopes", False) and source.requires_scopes:
        source = source.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])
    source.refresh(request)

    if settings.chat_service_account:
        try:
            impersonated = google.auth.impersonated_credentials.Credentials(
                source_credentials=source,
                target_principal=settings.chat_service_account,
                target_scopes=[DIRECTORY_SCOPE],
                lifetime=3600,
                quota_project_id=settings.gcp_project or None,
            )
            impersonated.refresh(request)
            if impersonated.token:
                return impersonated.token
        except Exception:
            logger.debug("directory_impersonation_failed", exc_info=True)

    scoped = source
    if getattr(source, "with_scopes", None):
        scoped = source.with_scopes([DIRECTORY_SCOPE])
    scoped.refresh(request)
    if not scoped.token:
        raise RuntimeError("Impossible d'obtenir un jeton Directory API")
    return scoped.token


def _user_cloud_token() -> str:
    import google.auth
    import google.auth.transport.requests

    request = google.auth.transport.requests.Request()
    source, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if getattr(source, "requires_scopes", False) and source.requires_scopes:
        source = source.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])
    source.refresh(request)
    if not source.token:
        raise RuntimeError("ADC utilisateur indisponible")
    return source.token


def _chat_app_token() -> str:
    import google.auth
    import google.auth.impersonated_credentials
    import google.auth.transport.requests

    from app.config import get_settings

    settings = get_settings()
    request = google.auth.transport.requests.Request()
    source, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if getattr(source, "requires_scopes", False) and source.requires_scopes:
        source = source.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])
    source.refresh(request)

    if settings.chat_service_account:
        credentials = google.auth.impersonated_credentials.Credentials(
            source_credentials=source,
            target_principal=settings.chat_service_account,
            target_scopes=[CHAT_BOT_SCOPE],
            lifetime=3600,
            quota_project_id=settings.gcp_project or None,
        )
    else:
        credentials, _ = google.auth.default(scopes=[CHAT_BOT_SCOPE])
    credentials.refresh(request)
    if not credentials.token:
        raise RuntimeError("Impossible d'obtenir un jeton pour Google Chat")
    return credentials.token
