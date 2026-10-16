"""Dossiers clients : boucle Gemini + tools MCP, confirmation par carte (spec admin.jin.fr §11)."""

from typing import Any

from google.genai import types

from app.core.chat_client import FakeChatClient
from app.dossiers.agent import confirm_pending, run_turn
from app.dossiers.cards import CONFIRM_ACTION
from app.dossiers.handlers import handle_card_click
from app.dossiers.mcp_client import ToolResult
from app.dossiers.session import DossierSession, MemoryDossierStore

SPACE = "spaces/DM1"
EMAIL = "rponceau@jin.fr"


def _response(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])


def _call(name: str, args: dict[str, Any]) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args, id=f"id-{name}"))


class FakeLLM:
    def __init__(self, *responses: types.GenerateContentResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, list[Any]]] = []

    def generate(self, system: str, contents: list[Any], tools: list[dict[str, Any]]) -> types.GenerateContentResponse:
        self.calls.append((system, contents))
        return self.responses.pop(0)


class FakeMCP:
    def __init__(self, results: dict[str, ToolResult]) -> None:
        self.results = results
        self.called: list[tuple[str, dict[str, Any]]] = []

    def describe(self):
        return [{"name": name, "description": "", "inputSchema": {"type": "object", "properties": {}}} for name in self.results], "Instructions serveur."

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.called.append((name, arguments))
        return self.results[name]


def test_tool_results_are_fed_back_to_gemini() -> None:
    session = DossierSession(space_id=SPACE, user_email=EMAIL)
    llm = FakeLLM(
        _response(_call("rechercher_client", {"nom": "Crédit Agricole"})),
        _response(types.Part(text="J'ai trouvé _credit-agricole. C'est celui-là ?")),
    )
    mcp = FakeMCP({"rechercher_client": ToolResult(False, "", {"candidats": [{"name": "_credit-agricole"}]})})
    result = run_turn(session, "il me faut un dossier client pour Crédit Agricole", llm=llm, mcp=mcp)

    assert mcp.called == [("rechercher_client", {"nom": "Crédit Agricole"})]
    assert result.replies[-1].text == "J'ai trouvé _credit-agricole. C'est celui-là ?"
    assert EMAIL in llm.calls[0][0]  # la personne est connue de Gemini, sans e-mail demandé
    # Historique : message, appel, réponse du tool, réponse finale.
    assert len(session.contents) == 4


def test_request_creation_waits_for_card_confirmation() -> None:
    session = DossierSession(space_id=SPACE, user_email=EMAIL)
    args = {"display_name": "Crédit Agricole Assurances", "technical_name": "_credit-agricole-assurances", "jinners": ["a@jin.fr"]}
    llm = FakeLLM(_response(_call("creer_demande_dossier_client", args)))
    mcp = FakeMCP({"creer_demande_dossier_client": ToolResult(False, "", {"status": "a_valider", "message": "Demande enregistrée."})})
    result = run_turn(session, "c'est bon", llm=llm, mcp=mcp)

    assert mcp.called == []  # rien n'est créé sans clic
    assert session.pending is not None and session.pending.name == "creer_demande_dossier_client"
    card = result.replies[-1].cards[0]["card"]
    buttons = card["sections"][0]["widgets"][-1]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Confirmer", "Modifier"]

    confirmed = confirm_pending(session, mcp=mcp)
    assert mcp.called == [("creer_demande_dossier_client", args)]
    assert confirmed.replies[-1].text == "Demande enregistrée."
    assert session.active is False


def test_only_the_requester_can_confirm() -> None:
    store = MemoryDossierStore()
    session = DossierSession(space_id=SPACE, user_email=EMAIL)
    llm = FakeLLM(_response(_call("demander_annees_manquantes", {"dossier_url": "https://drive.google.com/drive/folders/x"})))
    mcp = FakeMCP({"demander_annees_manquantes": ToolResult(False, "", {"message": "ok"})})
    run_turn(session, "crée 2027", llm=llm, mcp=mcp)
    store.save(session)
    chat = FakeChatClient()

    response = handle_card_click(SPACE, {"email": "autre@jin.fr"}, CONFIRM_ACTION, chat, store, mcp=mcp)
    assert response is None
    assert mcp.called == []
    assert "Seule la personne" in chat.messages[-1][1]

    response = handle_card_click(SPACE, {"email": EMAIL}, CONFIRM_ACTION, chat, store, mcp=mcp)
    assert response["actionResponse"]["type"] == "UPDATE_MESSAGE"
    assert mcp.called and mcp.called[0][0] == "demander_annees_manquantes"


def test_solicitation_context_reaches_gemini() -> None:
    session = DossierSession(space_id=SPACE, user_email=EMAIL, solicitation_id="sol-1", solicitation_context="Nouveau projet Sephora")
    llm = FakeLLM(_response(types.Part(text="Bonjour, un admin a besoin d'un dossier client pour Sephora.")))
    run_turn(session, None, llm=llm, mcp=FakeMCP({}))
    assert "sol-1" in llm.calls[0][0] and "Nouveau projet Sephora" in llm.calls[0][0]
