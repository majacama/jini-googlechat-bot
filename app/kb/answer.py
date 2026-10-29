"""Cas A : la question part à l'agent « jinbot » d'agent.jin.fr (app/kb/agent_jin.py)."""

import logging
from dataclasses import dataclass, field

from app.kb.types import KbHit

logger = logging.getLogger(__name__)


@dataclass
class KbAnswer:
    text: str
    sources: list[KbHit] = field(default_factory=list)
    found: bool = False


def answer_from_knowledge_base(
    question: str, history: list[dict] | None = None, acting_user: str | None = None
) -> KbAnswer:
    """Point d'entrée production. Une AgentJinError remonte : le bot affiche son message d'indisponibilité."""
    from app.kb.agent_jin import ask_agent_jin

    if not acting_user:
        logger.warning("kb_agent_jin_no_acting_user")
        return KbAnswer("Je n'arrive pas à identifier ton compte, réessaie dans un instant.")
    return ask_agent_jin(question, history, acting_user)
