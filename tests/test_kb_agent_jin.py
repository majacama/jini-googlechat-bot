"""Cas A par agent.jin.fr : contrat de /v1/agents/jinbot/ask."""

from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.kb import agent_jin, answer
from app.kb.agent_jin import AgentJinError, ask_agent_jin
from app.kb.answer import KbAnswer


class Response:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "agent_jin_key", "jinag_test")
    return s


def test_ask_sends_question_history_and_acting_user(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def post(url: str, **kw: Any) -> Response:
        calls.append({"url": url, **kw})
        return Response(
            200,
            {
                "answerable": True,
                "answer": "Malakoff.",
                "sources": [{"name": "Notice prévoyance.pdf", "link": "https://drive/1", "excerpt": "Malakoff Humanis", "score": 0.81}],
                "run_id": "r1",
            },
        )

    monkeypatch.setattr(agent_jin.httpx, "post", post)
    recent = [{"question": "Q1", "answer": "R1", "at": 1}, {"question": "", "answer": "x"}]
    result = ask_agent_jin("Qui est l'assureur prévoyance ?", recent, "marie.martin@jin.fr")
    assert result.found and result.text == "Malakoff."
    assert result.sources[0].name == "Notice prévoyance.pdf" and result.sources[0].link == "https://drive/1"
    call = calls[0]
    assert call["url"] == "https://agent.jin.fr/v1/agents/jinbot/ask"
    assert call["headers"] == {"authorization": "Bearer jinag_test", "x-acting-user": "marie.martin@jin.fr"}
    assert call["json"]["history"] == [{"question": "Q1", "answer": "R1"}]
    assert call["json"]["channel"] == "chat"


def test_unanswerable_question_is_not_an_error(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_jin.httpx, "post", lambda url, **kw: Response(200, {"answerable": False, "answer": "", "sources": []})
    )
    result = ask_agent_jin("q", None, "a@jin.fr")
    assert not result.found and "rien trouvé" in result.text


def test_http_errors_and_timeouts_raise(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_jin.httpx, "post", lambda url, **kw: Response(504, {"error": {"code": "timeout", "message": "trop long"}})
    )
    with pytest.raises(AgentJinError, match="504 timeout"):
        ask_agent_jin("q", None, "a@jin.fr")

    def boom(url: str, **kw: Any) -> Response:
        raise httpx.ReadTimeout("lent")

    monkeypatch.setattr(agent_jin.httpx, "post", boom)
    with pytest.raises(AgentJinError, match="injoignable"):
        ask_agent_jin("q", None, "a@jin.fr")


def test_errors_reach_the_bot_without_fallback(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*a: Any, **k: Any) -> KbAnswer:
        raise AgentJinError("agent.jin.fr 503")

    monkeypatch.setattr(agent_jin, "ask_agent_jin", failing)
    # L'erreur remonte : le bot affiche son message d'indisponibilité.
    with pytest.raises(AgentJinError):
        answer.answer_from_knowledge_base("q", None, acting_user="a@jin.fr")


def test_unknown_acting_user_is_not_sent(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(agent_jin, "ask_agent_jin", lambda *a, **k: called.append("agent") or KbAnswer("agent"))
    result = answer.answer_from_knowledge_base("q", None, acting_user=None)
    assert called == [] and not result.found
