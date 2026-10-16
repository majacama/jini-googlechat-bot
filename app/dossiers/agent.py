"""Boucle Gemini + tools MCP pour les dossiers clients (spec §11).

Gemini choisit les tools du serveur MCP admin.jin.fr ; le code garde la main sur ce qui
engage : un tool qui crée une demande n'est jamais exécuté directement, le bot envoie
d'abord une carte « Confirmer / Modifier » et n'appelle le tool qu'au clic.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from app.config import get_settings
from app.dossiers.cards import confirmation_card
from app.dossiers.mcp_client import AdminMcpClient, McpError
from app.dossiers.session import DossierSession, PendingConfirmation

logger = logging.getLogger(__name__)

# Tools qui créent une demande : confirmation par clic obligatoire.
CONFIRM_TOOLS = {"creer_demande_dossier_client", "demander_annees_manquantes"}
MAX_TOOL_ROUNDS = 5

BOT_INSTRUCTIONS = """Tu es Jinbot, l'assistant JIN sur Google Chat. Tutoiement, ton direct et bref, en français.
Une question à la fois. Montre les liens Drive quand tu présentes des dossiers clients.
Personne qui t'écrit : {email}. Date du jour : {today}.
Quand tu as toutes les informations d'une demande, appelle le tool de création : le bot
affichera lui-même une carte de confirmation, n'ajoute pas de récapitulatif.
"""


@dataclass
class Reply:
    text: str | None = None
    cards: list[dict[str, Any]] | None = None


@dataclass
class TurnResult:
    replies: list[Reply] = field(default_factory=list)


class DossierLLM(Protocol):
    def generate(self, system: str, contents: list[Any], tools: list[dict[str, Any]]) -> Any: ...


class GeminiDossierLLM:
    def generate(self, system: str, contents: list[Any], tools: list[dict[str, Any]]) -> Any:
        from google import genai
        from google.genai import types

        settings = get_settings()
        client = genai.Client(vertexai=True, project=settings.gcp_project or None, location=settings.gcp_region)
        declarations = [
            types.FunctionDeclaration(name=t["name"], description=t.get("description", ""), parameters_json_schema=t["inputSchema"])
            for t in tools
        ]
        return client.models.generate_content(
            model=settings.dossier_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                thinking_config=types.ThinkingConfig(thinking_budget=512),
            ),
        )


def _to_contents(session: DossierSession) -> list[Any]:
    from google.genai import types

    return [types.Content.model_validate(c) for c in session.contents]


def _remember(session: DossierSession, content: Any) -> None:
    session.contents.append(content.model_dump(mode="json", exclude_none=True))


def _user_content(text: str) -> Any:
    from google.genai import types

    return types.Content(role="user", parts=[types.Part(text=text)])


def _tool_response(name: str, call_id: str | None, payload: dict[str, Any]) -> Any:
    from google.genai import types

    return types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(name=name, id=call_id, response=payload))],
    )


def _payload(result) -> dict[str, Any]:
    if result.is_error:
        return {"erreur": result.text}
    return {"resultat": result.data if result.data is not None else result.text}


def system_prompt(session: DossierSession, server_instructions: str) -> str:
    text = BOT_INSTRUCTIONS.format(email=session.user_email, today=date.today().isoformat()) + "\n" + server_instructions
    if session.solicitation_id:
        text += (
            f"\n\nSollicitation en cours (mode 2) : identifiant {session.solicitation_id}. "
            f"Contexte donné par l'admin : {session.solicitation_context or '—'}. "
            "Passe sollicitation_id au tool de création. Si la personne dit que ce n'est pas nécessaire, "
            "appelle decliner_sollicitation ; si elle dit de voir avec un autre directeur, demande son e-mail "
            "et appelle rediriger_sollicitation."
        )
    return text


def run_turn(
    session: DossierSession,
    user_text: str | None,
    llm: DossierLLM | None = None,
    mcp: AdminMcpClient | None = None,
) -> TurnResult:
    """Ajoute le message de la personne et fait avancer la conversation."""
    llm = llm or GeminiDossierLLM()
    mcp = mcp or AdminMcpClient(session.user_email)
    result = TurnResult()
    if user_text:
        _remember(session, _user_content(user_text))

    try:
        tools, instructions = mcp.describe()
    except McpError:
        logger.exception("mcp_describe_failed")
        result.replies.append(Reply(text="Je n'arrive pas à joindre admin.jin.fr pour le moment. Réessaie dans un instant."))
        return result
    system = system_prompt(session, instructions)

    for _ in range(MAX_TOOL_ROUNDS):
        response = llm.generate(system, _to_contents(session), tools)
        candidate = response.candidates[0] if response.candidates else None
        content = candidate.content if candidate else None
        if content is None or not content.parts:
            result.replies.append(Reply(text="Je n'ai pas bien compris, peux-tu reformuler ?"))
            return result
        _remember(session, content)

        calls = [p.function_call for p in content.parts if p.function_call]
        texts = [p.text for p in content.parts if p.text and not getattr(p, "thought", False)]
        if not calls:
            result.replies.append(Reply(text="\n".join(texts).strip() or "…"))
            return result

        for call in calls:
            args = dict(call.args or {})
            if call.name in CONFIRM_TOOLS:
                # Le code, pas Gemini, fait confirmer la demande (spec §11.1).
                session.pending = PendingConfirmation(name=call.name, args=args, call_id=call.id)
                if texts:
                    result.replies.append(Reply(text="\n".join(texts).strip()))
                result.replies.append(Reply(cards=[confirmation_card(call.name, args, session.user_email)]))
                return result
            try:
                tool_result = mcp.call_tool(call.name, args)
                payload = _payload(tool_result)
            except McpError as error:
                logger.exception("mcp_call_failed", extra={"tool": call.name})
                payload = {"erreur": f"Service indisponible : {error}"}
            _remember(session, _tool_response(call.name, call.id, payload))

    result.replies.append(Reply(text="Je n'arrive pas à conclure. Peux-tu reformuler ta demande ?"))
    return result


def confirm_pending(session: DossierSession, mcp: AdminMcpClient | None = None) -> TurnResult:
    """Clic « Confirmer » : le bot appelle le tool de création mis en attente."""
    mcp = mcp or AdminMcpClient(session.user_email)
    result = TurnResult()
    pending = session.pending
    if pending is None:
        result.replies.append(Reply(text="Il n'y a plus de demande à confirmer."))
        return result
    session.pending = None
    try:
        tool_result = mcp.call_tool(pending.name, pending.args)
    except McpError:
        logger.exception("mcp_confirm_failed", extra={"tool": pending.name})
        result.replies.append(Reply(text="Je n'arrive pas à enregistrer la demande pour le moment. Réessaie dans un instant."))
        return result
    _remember(session, _tool_response(pending.name, pending.call_id, _payload(tool_result)))

    if tool_result.is_error:
        result.replies.append(Reply(text=f"La demande n'a pas pu être enregistrée : {tool_result.text}"))
        return result
    data = tool_result.data if isinstance(tool_result.data, dict) else {}
    message = data.get("message") or "Demande enregistrée."
    result.replies.append(Reply(text=message))
    session.active = False
    return result


def modify_pending(session: DossierSession, llm: DossierLLM | None = None, mcp: AdminMcpClient | None = None) -> TurnResult:
    """Clic « Modifier » : la conversation reprend pour corriger la demande."""
    pending = session.pending
    session.pending = None
    if pending is not None:
        _remember(session, _tool_response(pending.name, pending.call_id, {"annule": "La personne veut modifier la demande avant de la confirmer."}))
    return run_turn(session, "Je veux modifier la demande.", llm=llm, mcp=mcp)
