"""Fil de travail admin.jin.fr → Google Chat (spec admin.jin.fr §11.3 à §11.5).

Cloud Scheduler appelle /tasks/bot-feed chaque minute : le bot lit le fil, envoie chaque
message (DM au directeur ou au demandeur, carte ou suivi dans IT Operations), puis le
confirme (ack). Un message non confirmé revient au passage suivant.
"""

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.core.chat_client import ChatApiError

logger = logging.getLogger(__name__)

VALIDATE_ACTION = "demande_valider"
REFUSE_ACTION = "demande_refuser"

KIND_LABELS = {"creation": "Nouveau dossier client", "annees": "Années manquantes", "membres": "Ajout de membres"}
STATUS_LABELS = {
    "a_valider": "À valider",
    "en_cours": "Validée, en cours",
    "terminee": "Terminée",
    "erreur": "En erreur",
    "refusee": "Refusée",
    "abandonnee": "Abandonnée",
    "brouillon": "Directeur sollicité",
}
SOURCE_LABELS = {"ui": "interface", "api": "API", "mcp": "Claude (MCP)", "chat": "Google Chat", "furious": "Furious"}


class AdminApiError(RuntimeError):
    pass


class AdminApiClient:
    """API admin.jin.fr réservée au bot (jeton du bot)."""

    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 20.0) -> None:
        settings = get_settings()
        self.base = (base_url or settings.admin_jin_url).rstrip("/") + "/api/v1"
        self.token = token or settings.admin_jin_bot_token
        self.timeout = timeout

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None, acting_user: str | None = None) -> Any:
        if not self.token:
            raise AdminApiError("ADMIN_JIN_BOT_TOKEN n'est pas configuré.")
        headers = {"authorization": f"Bearer {self.token}"}
        if acting_user:
            headers["x-acting-user"] = acting_user
        response = httpx.request(method, self.base + path, headers=headers, json=json, timeout=self.timeout)
        if response.is_error:
            try:
                detail = response.json().get("error") or response.text
            except ValueError:
                detail = response.text
            raise AdminApiError(str(detail)[:300])
        return response.json()

    def feed(self) -> list[dict[str, Any]]:
        return self._request("GET", "/bot/feed")

    def ack(self, key: str, message: str | None = None) -> None:
        self._request("POST", "/bot/ack", json={"key": key, **({"message": message} if message else {})})

    def decide(self, request_id: str, decision: str, acting_user: str) -> dict[str, Any]:
        return self._request("POST", f"/requests/{request_id}/decision", json={"decision": decision}, acting_user=acting_user)


# --- Textes -------------------------------------------------------------------------


def _name(req: dict[str, Any]) -> str:
    return req.get("technical_name") or req.get("display_name") or "?"


def _manager(req: dict[str, Any]) -> str:
    email = req.get("manager_email") or "—"
    return f"{req['manager_name']} <{email}>" if req.get("manager_name") else email


def summary_card(item: dict[str, Any], lines: list[tuple[str, str]], with_request: bool = False) -> dict[str, Any]:
    """Carte compacte : quelques lignes et des boutons vers le dossier, l'espace Chat, la demande."""
    req = item["request"]
    links = item.get("links") or {}
    widgets: list[dict[str, Any]] = [
        {"decoratedText": {"topLabel": label, "text": text or "—", "wrapText": True}} for label, text in lines
    ]
    buttons = []
    if links.get("dossier"):
        buttons.append({"text": "Dossier", "onClick": {"openLink": {"url": links["dossier"]}}})
    if links.get("espace_chat"):
        buttons.append({"text": "Espace Chat", "onClick": {"openLink": {"url": links["espace_chat"]}}})
    if with_request and links.get("demande"):
        buttons.append({"text": "Demande", "onClick": {"openLink": {"url": links["demande"]}}})
    if buttons:
        widgets.append({"buttonList": {"buttons": buttons}})
    return {
        "cardId": f"suivi-{req['id']}",
        "card": {
            "header": {"title": KIND_LABELS.get(req.get("kind"), req.get("kind")), "subtitle": _name(req)},
            "sections": [{"widgets": widgets}],
        },
    }


def notification_text(item: dict[str, Any]) -> str:
    req = item["request"]
    name = _name(req)
    kind = req.get("kind")
    match item.get("notification"):
        case "demande":
            return (
                f"{req.get('requested_by')} a fait une demande ({KIND_LABELS.get(kind, kind).lower()}) "
                f"pour le dossier client *{name}* à ton nom : tu en deviens le gestionnaire. "
                "Je te préviens quand il est prêt."
            )
        case "pret":
            what = (
                f"Les années manquantes du dossier client *{name}* sont créées."
                if kind == "annees"
                else f"Le dossier client *{name}* est prêt."
            )
            return what + " Tu en es le gestionnaire."
        case "information":
            return f"Pour information : {_manager(req)} devient gestionnaire du dossier client *{name}* à ta place."
        case "abandon":
            return f"{_manager(req)} indique que le dossier client *{name}* n'est pas nécessaire : la demande est abandonnée."
        case "redirection":
            return f"La demande de dossier client *{name}* a été redirigée vers {_manager(req)}."
    return f"Dossier client *{name}* : {STATUS_LABELS.get(req.get('status'), req.get('status'))}."


def status_text(item: dict[str, Any]) -> str:
    req = item["request"]
    label = KIND_LABELS.get(req.get("kind"), req.get("kind")).lower()
    name = _name(req)
    match req.get("status"):
        case "en_cours":
            return f"Ta demande ({label}) pour *{name}* est validée : c'est en cours."
        case "terminee":
            return f"C'est fait : {label} pour *{name}*."
        case "erreur":
            return f"Ta demande ({label}) pour *{name}* a rencontré un problème. IT Operations est prévenu."
        case "refusee":
            return f"Ta demande ({label}) pour *{name}* a été refusée par un admin."
    return f"Ta demande pour *{name}* : {STATUS_LABELS.get(req.get('status'), req.get('status'))}."


def followup_text(item: dict[str, Any]) -> str:
    """Fin d'une demande validée sans carte (par un admin) : une ligne dans IT Operations."""
    req = item["request"]
    label = KIND_LABELS.get(req.get("kind"), req.get("kind"))
    mark = "⚠️ En erreur" if req.get("status") == "erreur" else "✅ Terminée"
    return f"{mark} · {label} · *{_name(req)}*"


def followup_card(item: dict[str, Any]) -> dict[str, Any]:
    req = item["request"]
    lines = [
        ("Statut", STATUS_LABELS.get(req.get("status"), req.get("status"))),
        ("Gestionnaire", _manager(req)),
        ("Demandée par", f"{req.get('requested_by')} ({SOURCE_LABELS.get(req.get('source'), req.get('source'))})"),
    ]
    if req.get("validated_by") and req.get("validated_by") != req.get("requested_by"):
        lines.append(("Validée par", req["validated_by"]))
    if req.get("status") == "erreur":
        lines.append(("Erreur", req.get("error") or "—"))
    return summary_card(item, lines, with_request=True)


def request_card(req: dict[str, Any], links: dict[str, Any]) -> dict[str, Any]:
    """Carte IT Operations d'une demande ; boutons de décision tant qu'elle est à valider."""
    kind = req.get("kind")
    title = {"creation": "Nouveau dossier client à valider", "annees": "Années manquantes à créer"}.get(kind, "Ajout de membres à valider")

    def line(label: str, text: str) -> dict[str, Any]:
        return {"decoratedText": {"topLabel": label, "text": text or "—", "wrapText": True}}

    widgets: list[dict[str, Any]] = [line("Statut", STATUS_LABELS.get(req.get("status"), req.get("status")))]
    if kind == "creation":
        widgets.append(line("Niveau de sécurité", str(req.get("security_level"))))
    widgets.append(line("Gestionnaire", _manager(req)))
    if req.get("previous_manager_email") and req.get("previous_manager_email") != req.get("manager_email"):
        widgets.append(line("Ancien gestionnaire", req.get("previous_manager_name") or req["previous_manager_email"]))
    widgets.append(line("Demandée par", f"{req.get('requested_by')} ({SOURCE_LABELS.get(req.get('source'), req.get('source'))})"))
    widgets.append(line("Jinners ajoutés au groupe" if kind == "annees" else "Jinners", ", ".join(req.get("jinners") or []) or "—"))
    widgets.append(line("Externes", ", ".join(req.get("externals") or []) or "—"))
    if req.get("validated_by"):
        widgets.append(line("Décision", req["validated_by"]))
    if req.get("status") == "erreur" and req.get("error"):
        widgets.append(line("Erreur", req["error"]))

    buttons: list[dict[str, Any]] = []
    if req.get("status") == "a_valider":
        params = [{"key": "request_id", "value": req["id"]}]
        buttons += [
            {"text": "Valider et lancer", "onClick": {"action": {"function": VALIDATE_ACTION, "parameters": params}}},
            {"text": "Refuser", "onClick": {"action": {"function": REFUSE_ACTION, "parameters": params}}},
        ]
    buttons.append({"text": "Ouvrir", "onClick": {"openLink": {"url": links.get("demande")}}})
    if links.get("dossier"):
        buttons.append({"text": "Dossier", "onClick": {"openLink": {"url": links["dossier"]}}})
    widgets.append({"buttonList": {"buttons": buttons}})
    return {
        "cardId": f"demande-{req['id']}",
        "card": {
            "header": {"title": title, "subtitle": f"{req.get('display_name')} · {req.get('technical_name')}"},
            "sections": [{"widgets": widgets}],
        },
    }


# --- Livraison ------------------------------------------------------------------------


def _send_dm(chat_client, email: str, text: str, cards: list[dict[str, Any]] | None = None) -> None:
    space = chat_client.create_dm(email)
    chat_client.send_message(space, text, cards=cards)


def deliver_item(item: dict[str, Any], chat_client, admin: AdminApiClient, it_ops_space: str) -> bool:
    """Envoie un élément du fil et le confirme. Renvoie False s'il doit attendre (mode 2)."""
    kind = item["type"]
    req = item["request"]
    message_name = None

    if kind in {"notification", "statut"}:
        text = notification_text(item) if kind == "notification" else status_text(item)
        done = item.get("notification") == "pret" or (kind == "statut" and req.get("status") == "terminee")
        cards = [summary_card(item, [("Gestionnaire", _manager(req))])] if done else None
        try:
            _send_dm(chat_client, item["to"], text, cards)
        except ChatApiError as error:
            # Pas de conversation avec Jinbot : IT Operations relaie, pour ne pas bloquer le fil.
            logger.warning("feed_dm_failed", extra={"to": item["to"], "error": str(error)})
            chat_client.send_message(
                it_ops_space, f"Je n'ai pas pu écrire à {item['to']} (pas de conversation avec Jinbot). Message :\n{text}", cards=cards
            )
    elif kind == "carte":
        posted = chat_client.send_message(it_ops_space, f"{KIND_LABELS.get(req.get('kind'))} : {_name(req)}", cards=[request_card(req, item["links"])])
        message_name = (posted or {}).get("name")
    elif kind == "carte_maj":
        chat_client.update_message(req["chat_card_message"], cards=[request_card(req, item["links"])])
    elif kind == "suivi":
        chat_client.send_message(it_ops_space, followup_text(item), cards=[followup_card(item)])
    else:
        # sollicitation, relance, alerte_admin : mode 2, pas encore livré par le bot.
        return False

    admin.ack(item["key"], message_name)
    return True


def deliver_feed(chat_client, admin: AdminApiClient | None = None) -> dict[str, int]:
    admin = admin or AdminApiClient()
    it_ops_space = get_settings().it_ops_space
    counts = {"envoyes": 0, "en_attente": 0, "erreurs": 0}
    for item in admin.feed():
        try:
            if deliver_item(item, chat_client, admin, it_ops_space):
                counts["envoyes"] += 1
            else:
                counts["en_attente"] += 1
        except (ChatApiError, AdminApiError, httpx.HTTPError) as error:
            counts["erreurs"] += 1
            logger.error("feed_item_failed", extra={"key": item.get("key"), "error": str(error)})
    if counts["envoyes"] or counts["erreurs"]:
        logger.info("feed_delivered", extra=counts)
    return counts


def handle_decision_click(sender_email: str | None, function: str, params: dict[str, str], chat_client, space_id: str, admin: AdminApiClient | None = None) -> dict[str, Any] | None:
    """Clic « Valider et lancer » / « Refuser » sur la carte IT Operations.

    Le code du bot transmet la décision avec l'e-mail de la personne qui clique ;
    admin.jin.fr vérifie qu'elle est admin.
    """
    request_id = params.get("request_id")
    if not request_id or not sender_email:
        return None
    admin = admin or AdminApiClient()
    decision = "valider" if function == VALIDATE_ACTION else "refuser"
    try:
        row = admin.decide(request_id, decision, sender_email)
    except (AdminApiError, httpx.HTTPError) as error:
        chat_client.send_message(space_id, f"Décision non prise en compte : {error}")
        return None
    links = {"demande": f"{admin.base.removesuffix('/api/v1')}/demandes#{request_id}", "dossier": None}
    return {"actionResponse": {"type": "UPDATE_MESSAGE"}, "cardsV2": [request_card(row, links)]}
