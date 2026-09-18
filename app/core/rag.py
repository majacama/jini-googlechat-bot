"""RAG (cas A) : recherche sur le corpus Drive via Vertex AI Search / Agent
Search. Voir docs/SPEC-Jin-Investigator-Cible-V2.md section 6.

Point de vigilance non tranché a l'implementation : userInfo.userId est cense
appliquer les droits Drive de l'utilisateur a la requete (query-time), mais
ca n'a pu etre verifie qu'avec un compte super admin proprietaire du document
de test - jamais confirme avec un utilisateur non-admin reellement restreint.
"""

import html
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"</?b>")


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


def _access_token() -> str:
    import google.auth
    import google.auth.transport.requests

    request = google.auth.transport.requests.Request()
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(request)
    return credentials.token


def search_corpus(query: str, user_email: str | None = None, page_size: int = 5) -> list[RagPassage]:
    settings = get_settings()
    if not settings.discovery_engine_id:
        logger.warning("rag_not_configured")
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
    if user_email:
        # Cense restreindre les resultats aux droits Drive de cet utilisateur
        # (voir l'avertissement en tete de fichier).
        payload["userInfo"] = {"userId": user_email}

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {_access_token()}",
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
