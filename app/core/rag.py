"""RAG (cas A) : recherche sur le corpus Drive via Vertex AI Search / Agent
Search. Voir docs/SPEC-Jin-Investigator-Cible-V2.md section 6.

Un data store Workspace (connecteur Drive) refuse categoriquement les
requetes de recherche authentifiees en simple compte de service (HTTP 403
"Search using service account credentials is not supported for workspace
datastores", decouvert le 2026-09-18 en testant en reel). Il faut une vraie
delegation a l'echelle du domaine (domain-wide delegation) : le jeton doit
representer l'utilisateur Chat qui pose la question (via un JWT signe avec
`sub=user_email`), pas le compte de service qui l'emet. Implemente ici sans
jamais telecharger de cle privee (IAM Credentials API signJwt), scope etroit
`cloud_search.query` plutot que `cloud-platform` (voir Cible V2 section 6).

Prerequis cote Admin Workspace (a faire une fois, par un super admin) :
autoriser la delegation a l'echelle du domaine pour le Client ID du compte
`agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com` avec le scope
`https://www.googleapis.com/auth/cloud_search.query`.

Point de vigilance non tranché a l'implementation : userInfo.userId est cense
*en plus* de la delegation ci-dessus, preciser le contexte de recherche -
mais son role exact une fois la delegation en place n'a pas ete reverifie.
A confirmer avec un vrai test utilisateur non-admin.
"""

import html
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"</?b>")

CLOUD_SEARCH_QUERY_SCOPE = "https://www.googleapis.com/auth/cloud_search.query"
IAM_CREDENTIALS_API = "https://iamcredentials.googleapis.com/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass
class RagPassage:
    title: str
    link: str
    snippet: str


def _clean_text(text: str) -> str:
    # La reponse melange deux styles d'echappement pour <b>...</b> (mise en
    # evidence du terme recherche) selon le champ : a normaliser avant de
    # l'envoyer dans Chat, qui n'interprete pas ce HTML.
    return _TAG_RE.sub("", html.unescape(text or "")).strip()


def _caller_access_token() -> str:
    """Jeton de l'identite du service Cloud Run lui-meme, utilise uniquement
    pour s'authentifier aupres de l'API IAM Credentials (signJwt) - jamais
    envoye tel quel a Discovery Engine, un data store Workspace le refuse."""
    import google.auth
    import google.auth.transport.requests

    request = google.auth.transport.requests.Request()
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(request)
    return credentials.token


def _delegated_access_token(user_email: str) -> str:
    """Jeton qui represente reellement `user_email` (delegation a l'echelle
    du domaine), via IAM Credentials API signJwt - sans jamais manipuler de
    cle privee de compte de service."""
    settings = get_settings()
    sa_email = settings.chat_service_account
    if not sa_email:
        raise RuntimeError("CHAT_SERVICE_ACCOUNT non configure, requis pour la delegation de domaine")

    now = int(time.time())
    claims = {
        "iss": sa_email,
        "scope": CLOUD_SEARCH_QUERY_SCOPE,
        "aud": OAUTH_TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
        "sub": user_email,
    }

    with httpx.Client(timeout=20.0) as client:
        sign_response = client.post(
            f"{IAM_CREDENTIALS_API}/projects/-/serviceAccounts/{sa_email}:signJwt",
            headers={
                "Authorization": f"Bearer {_caller_access_token()}",
                "Content-Type": "application/json",
            },
            json={"payload": json.dumps(claims)},
        )
    if sign_response.is_error:
        raise RuntimeError(f"signJwt a échoué ({sign_response.status_code}): {sign_response.text[:300]}")
    signed_jwt = sign_response.json()["signedJwt"]

    with httpx.Client(timeout=20.0) as client:
        token_response = client.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
        )
    if token_response.is_error:
        raise RuntimeError(
            f"échange du JWT délégué a échoué ({token_response.status_code}): {token_response.text[:300]}"
        )
    return token_response.json()["access_token"]


def search_corpus(query: str, user_email: str | None = None, page_size: int = 5) -> list[RagPassage]:
    settings = get_settings()
    if not settings.discovery_engine_id:
        logger.warning("rag_not_configured")
        return []
    if not user_email:
        # Un data store Workspace exige une identite utilisateur reelle :
        # pas de repli possible sur le compte de service seul (403 garanti).
        logger.warning("rag_no_user_email")
        return []

    try:
        token = _delegated_access_token(user_email)
    except Exception:
        logger.exception("rag_delegation_failed", extra={"user_email": user_email})
        return []

    url = (
        f"https://{settings.discovery_engine_location}-discoveryengine.googleapis.com/v1alpha/"
        f"projects/{settings.gcp_project}/locations/{settings.discovery_engine_location}/"
        f"collections/default_collection/engines/{settings.discovery_engine_id}/"
        "servingConfigs/default_search:search"
    )
    payload: dict[str, Any] = {
        "query": query,
        "pageSize": page_size,
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "languageCode": "fr",
        "contentSearchSpec": {"extractiveContentSpec": {"maxExtractiveAnswerCount": 1}},
    }
    payload["userInfo"] = {"userId": user_email}

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception:
        logger.exception("rag_search_request_failed")
        return []

    if response.is_error:
        logger.warning(
            "rag_search_failed",
            extra={"status": response.status_code, "body": response.text[:300]},
        )
        return []

    data = response.json()
    passages: list[RagPassage] = []
    for item in data.get("results", []):
        struct = (item.get("document") or {}).get("derivedStructData") or {}
        title = struct.get("title") or "(sans titre)"
        link = struct.get("link") or ""
        extractive = struct.get("extractive_answers") or []
        snippets = struct.get("snippets") or []
        if extractive:
            raw_snippet = extractive[0].get("content", "")
        elif snippets:
            raw_snippet = snippets[0].get("snippet", "")
        else:
            raw_snippet = ""
        passages.append(RagPassage(title=title, link=link, snippet=_clean_text(raw_snippet)))
    return passages


def build_rag_cards(passages: list[RagPassage]) -> list[dict[str, Any]]:
    """CardsV2 Google Chat : un card par document, avec bouton vers Drive."""
    cards: list[dict[str, Any]] = []
    for index, passage in enumerate(passages):
        widgets: list[dict[str, Any]] = []
        if passage.snippet:
            widgets.append({"textParagraph": {"text": passage.snippet}})
        if passage.link:
            widgets.append(
                {
                    "buttonList": {
                        "buttons": [
                            {
                                "text": "Ouvrir dans Drive",
                                "onClick": {"openLink": {"url": passage.link}},
                            }
                        ]
                    }
                }
            )
        cards.append(
            {
                "cardId": f"rag-result-{index}",
                "card": {
                    "header": {"title": passage.title},
                    "sections": [{"widgets": widgets}] if widgets else [],
                },
            }
        )
    return cards
