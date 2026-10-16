"""Fil de travail admin.jin.fr : notifications, carte et suivi IT Operations (spec §11)."""

from typing import Any

from app.core.chat_client import ChatApiError, FakeChatClient
from app.dossiers.feed import REFUSE_ACTION, VALIDATE_ACTION, deliver_feed, handle_decision_click
from app.routers.chat import parse_card_click

IT_OPS = "spaces/AAQAT7GKGxc"


def _request(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "req-1",
        "kind": "annees",
        "technical_name": "_natran",
        "display_name": "_natran",
        "status": "terminee",
        "source": "chat",
        "requested_by": "fdiaz@jin.fr",
        "validated_by": "fdiaz@jin.fr",
        "manager_email": "fdiaz@jin.fr",
        "manager_name": "Frédéric Diaz",
        "jinners": [],
        "externals": [],
        "security_level": 2,
        "error": None,
        "chat_card_message": None,
    }
    return {**base, **overrides}


def _item(type_: str, to: str | None = None, notification: str | None = None, **req: Any) -> dict[str, Any]:
    return {
        "key": f"req-1|{type_}|x",
        "type": type_,
        "to": to,
        "notification": notification,
        "request": _request(**req),
        "links": {"demande": "https://admin.jin.fr/demandes#req-1", "dossier": "https://drive.google.com/drive/folders/abc", "espace_chat": None},
    }


class FakeAdmin:
    base = "https://admin.jin.fr/api/v1"

    def __init__(self, items: list[dict[str, Any]] | None = None, decision: dict[str, Any] | None = None) -> None:
        self.items = items or []
        self.acks: list[tuple[str, str | None]] = []
        self.decision = decision
        self.decisions: list[tuple[str, str, str]] = []

    def feed(self) -> list[dict[str, Any]]:
        return self.items

    def ack(self, key: str, message: str | None = None) -> None:
        self.acks.append((key, message))

    def decide(self, request_id: str, decision: str, acting_user: str) -> dict[str, Any]:
        self.decisions.append((request_id, decision, acting_user))
        return self.decision


def test_ready_notification_goes_to_the_director_and_followup_to_it_ops() -> None:
    admin = FakeAdmin([_item("notification", to="fdiaz@jin.fr", notification="pret"), _item("suivi")])
    chat = FakeChatClient()
    counts = deliver_feed(chat, admin)

    assert counts == {"envoyes": 2, "en_attente": 0, "erreurs": 0}
    dm_space, dm_text = chat.messages[0]
    assert dm_space == "spaces/fake-fdiaz@jin.fr"
    assert "Les années manquantes du dossier client *_natran* sont créées" in dm_text
    # Liens en boutons de carte, jamais en clair (Chat afficherait un aperçu Drive).
    assert "http" not in dm_text
    dm_buttons = chat.cards_sent[0][0]["card"]["sections"][0]["widgets"][-1]["buttonList"]["buttons"]
    assert [b["text"] for b in dm_buttons] == ["Dossier"]
    space, text = chat.messages[1]
    assert space == IT_OPS and text == "✅ Terminée · Années manquantes · *_natran*"
    ops_buttons = chat.cards_sent[1][0]["card"]["sections"][0]["widgets"][-1]["buttonList"]["buttons"]
    assert [b["text"] for b in ops_buttons] == ["Dossier", "Demande"]
    assert [key for key, _ in admin.acks] == ["req-1|notification|x", "req-1|suivi|x"]


def test_validation_card_is_posted_with_buttons_and_its_message_acked() -> None:
    admin = FakeAdmin([_item("carte", status="a_valider", validated_by=None)])
    chat = FakeChatClient()
    deliver_feed(chat, admin)

    card = chat.cards_sent[0][0]["card"]
    buttons = card["sections"][0]["widgets"][-1]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons][:2] == ["Valider et lancer", "Refuser"]
    assert buttons[0]["onClick"]["action"]["parameters"] == [{"key": "request_id", "value": "req-1"}]
    assert admin.acks == [("req-1|carte|x", f"{IT_OPS}/messages/1")]


def test_card_update_replaces_the_existing_message() -> None:
    admin = FakeAdmin([_item("carte_maj", status="en_cours", chat_card_message=f"{IT_OPS}/messages/9")])
    chat = FakeChatClient()
    deliver_feed(chat, admin)
    assert chat.updates[0][0] == f"{IT_OPS}/messages/9"
    buttons = chat.updates[0][1][0]["card"]["sections"][0]["widgets"][-1]["buttonList"]["buttons"]
    assert "Valider et lancer" not in [b["text"] for b in buttons]


def test_unreachable_person_is_relayed_in_it_ops() -> None:
    class NoDm(FakeChatClient):
        def create_dm(self, user_email: str) -> str:
            raise ChatApiError("spaces.findDirectMessage", 404, "pas de DM")

    admin = FakeAdmin([_item("statut", to="x@jin.fr", status="en_cours")])
    chat = NoDm()
    deliver_feed(chat, admin)
    assert chat.messages[0][0] == IT_OPS and "x@jin.fr" in chat.messages[0][1]
    assert admin.acks  # le fil n'est pas bloqué


def test_solicitations_wait_for_mode_2() -> None:
    admin = FakeAdmin([_item("sollicitation", to="d@jin.fr", status="brouillon")])
    counts = deliver_feed(FakeChatClient(), admin)
    assert counts["en_attente"] == 1 and admin.acks == []


def test_decision_click_is_sent_with_the_clicker_email() -> None:
    admin = FakeAdmin(decision=_request(status="en_cours", validated_by="admin@jin.fr"))
    response = handle_decision_click("admin@jin.fr", VALIDATE_ACTION, {"request_id": "req-1"}, FakeChatClient(), IT_OPS, admin)
    assert admin.decisions == [("req-1", "valider", "admin@jin.fr")]
    assert response["actionResponse"]["type"] == "UPDATE_MESSAGE"


def test_card_click_parameters_are_parsed() -> None:
    event = {
        "type": "CARD_CLICKED",
        "space": {"name": IT_OPS},
        "user": {"name": "users/1", "email": "a@jin.fr"},
        "action": {"actionMethodName": REFUSE_ACTION, "parameters": [{"key": "request_id", "value": "req-1"}]},
    }
    function, space, sender, params = parse_card_click(event)
    assert (function, space, params) == (REFUSE_ACTION, IT_OPS, {"request_id": "req-1"})
