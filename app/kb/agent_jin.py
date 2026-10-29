"""Cas A par agent.jin.fr : la question part à l'agent « jinbot » de la plateforme
(POST /v1/agents/jinbot/ask), qui cherche dans ses RAG-Data-Sources et rédige la réponse.

Le bot s'authentifie avec sa clé d'application (AGENT_JIN_KEY, secret jinbot-agent-jin-fr-key)
et transmet l'e-mail de la personne (X-Acting-User), tracée dans les runs de la plateforme.
"""

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.kb.answer import KbAnswer
from app.kb.types import KbHit

logger = logging.getLogger(__name__)

NO_ANSWER = "Je n'ai rien trouvé dans les documents JIN pour cette question."


class AgentJinError(RuntimeError):
    """agent.jin.fr injoignable, délai dépassé ou réponse inattendue (pas « rien trouvé »)."""


def _history(recent: list[dict] | None) -> list[dict[str, str]]:
    """Échanges récents du canal, au format de la plateforme (les plus anciens d'abord)."""
    turns = []
    for turn in recent or []:
        question, answer = str(turn.get("question") or ""), str(turn.get("answer") or "")
        if question and answer:
            turns.append({"question": question[:2000], "answer": answer[:4000]})
    return turns[-4:]


def _hit(source: dict[str, Any]) -> KbHit:
    link = str(source.get("link") or "")
    return KbHit(
        file_id=link or str(source.get("name") or ""),
        name=str(source.get("name") or "Document"),
        link=link,
        chunk_index=0,
        content=str(source.get("excerpt") or ""),
        similarity=float(source.get("score") or 0.0),
    )


def ask_agent_jin(question: str, history: list[dict] | None, acting_user: str) -> KbAnswer:
    settings = get_settings()
    if not settings.agent_jin_key:
        raise AgentJinError("AGENT_JIN_KEY n'est pas configurée")
    try:
        response = httpx.post(
            f"{settings.agent_jin_url.rstrip('/')}/v1/agents/{settings.agent_jin_agent}/ask",
            headers={"authorization": f"Bearer {settings.agent_jin_key}", "x-acting-user": acting_user},
            json={"question": question[:4000], "history": _history(history), "channel": "chat"},
            timeout=settings.agent_jin_timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AgentJinError(f"agent.jin.fr injoignable : {type(exc).__name__}") from exc
    if response.status_code >= 400:
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        raise AgentJinError(f"agent.jin.fr {response.status_code} {error.get('code', '')} {error.get('message', '')}".strip())
    body = response.json()
    answer = str(body.get("answer") or "").strip()
    if not body.get("answerable") or not answer:
        return KbAnswer(answer or NO_ANSWER)
    sources = [_hit(s) for s in body.get("sources") or []]
    logger.info("kb_agent_jin_answer", extra={"run_id": body.get("run_id"), "sources": len(sources)})
    return KbAnswer(answer, sources, found=True)
