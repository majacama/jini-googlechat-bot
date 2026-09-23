import logging
from typing import Any

from app.core.chat_client import ChatApiError, resolve_sender_email
from app.core.llm import decide_next_action, decide_route
from app.core.process_registry import get_process_registry
from app.core.rag import build_rag_cards
from app.core.state_machine import (
    apply_action,
    opening_message,
    record_agent_message,
    record_user_message,
)
from app.core.validation import validate_field
from app.core.webhook import deliver_completion
from app.models.conversation_state import ConversationState
from app.kb.answer import answer_from_knowledge_base
from app.models.form_spec import Contact, FormSpec, derive_target_schema
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)


class ConversationAlreadyActive(Exception):
    """Un formulaire est deja in_progress sur cet espace ; on ne l'ecrase pas."""

    def __init__(self, space_id: str, form_id: str) -> None:
        self.space_id = space_id
        self.form_id = form_id
        super().__init__(f"Session active ({form_id}) sur {space_id}")


def build_initial_state(
    space_id: str,
    contact: Contact,
    form_spec: FormSpec,
    webhook_url: str,
    webhook_secret: str | None = None,
    field_values: dict[str, Any] | None = None,
) -> ConversationState:
    use_gate = form_spec.uses_interlocutor_gate()
    state = ConversationState(
        space_id=space_id,
        form_id=form_spec.form_id,
        contact=contact,
        form_spec=form_spec,
        target_schema=derive_target_schema(form_spec),
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        phase="interlocutor" if use_gate else "questionnaire",
    )
    for field_id, raw_value in (field_values or {}).items():
        field = form_spec.field_by_id(field_id)
        if field is None:
            logger.warning(
                "field_values_unknown_field", extra={"field_id": field_id, "form_id": form_spec.form_id}
            )
            continue
        result = validate_field(field, raw_value)
        if not result.ok:
            # Valeur fournie mais invalide : on ne la prend pas silencieusement,
            # la question sera posée normalement dans le questionnaire.
            logger.warning(
                "field_values_invalid",
                extra={"field_id": field_id, "form_id": form_spec.form_id, "error": result.error},
            )
            continue
        state.answers[field_id] = result.value

    if not use_gate:
        next_field = form_spec.next_pending_field(state.answers, state.skipped_field_ids)
        state.current_field_id = next_field.id if next_field else None

    return state


def begin_conversation(
    contact: Contact,
    form_spec: FormSpec,
    webhook_url: str,
    repo: ConversationRepo,
    chat_client,
    webhook_secret: str | None = None,
    field_values: dict[str, Any] | None = None,
) -> ConversationState:
    """Cas C (déclenchement externe, /start) : ouvre le DM puis lance la
    session. Seul ce cas peut pré-remplir des champs (field_values)."""
    space_id = chat_client.create_dm(contact.user_id or contact.user_email)
    return _start_session(
        space_id, contact, form_spec, webhook_url, repo, chat_client, webhook_secret, field_values
    )


def resume_in_space(
    space_id: str,
    contact: Contact,
    form_spec: FormSpec,
    webhook_url: str,
    repo: ConversationRepo,
    chat_client,
    webhook_secret: str | None = None,
) -> ConversationState:
    """Cas B (déclenchement depuis le chat) : le DM existe déjà, on ne le
    recrée pas — on lance juste la session dedans. Pas de field_values ici :
    seul /start (cas C) en fournit pour l'instant."""
    return _start_session(space_id, contact, form_spec, webhook_url, repo, chat_client, webhook_secret)


def _start_session(
    space_id: str,
    contact: Contact,
    form_spec: FormSpec,
    webhook_url: str,
    repo: ConversationRepo,
    chat_client,
    webhook_secret: str | None = None,
    field_values: dict[str, Any] | None = None,
) -> ConversationState:
    existing = repo.get(space_id)
    if existing is not None and existing.status == "in_progress":
        raise ConversationAlreadyActive(space_id=space_id, form_id=existing.form_id)
    state = build_initial_state(
        space_id=space_id,
        contact=contact,
        form_spec=form_spec,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        field_values=field_values,
    )
    repo.save(state)
    send_opening(state, repo, chat_client)
    logger.info(
        "conversation_started",
        extra={
            "space_id": space_id,
            "form_id": state.form_id,
            "phase": state.phase,
            "field_id": state.current_field_id,
        },
    )
    return state


def send_opening(state: ConversationState, repo: ConversationRepo, chat_client) -> None:
    text = opening_message(state)
    record_agent_message(state, text, state.current_field_id)
    repo.save(state)
    chat_client.send_message(state.space_id, text)
    logger.info(
        "opening_sent",
        extra={"space_id": state.space_id, "form_id": state.form_id, "field_id": state.current_field_id},
    )


def process_user_message(
    space_id: str,
    text: str,
    repo: ConversationRepo,
    chat_client,
    sender: dict[str, Any] | None = None,
) -> None:
    state = repo.get(space_id)
    if state is None:
        _route_new_conversation(space_id, text, sender or {}, repo, chat_client)
        return
    if state.status != "in_progress":
        logger.info("ignored_terminal_state", extra={"space_id": space_id, "status": state.status})
        return

    record_user_message(state, text)
    try:
        action = decide_next_action(state.form_spec, state, text)
    except Exception:
        logger.exception("llm_failed", extra={"space_id": space_id})
        repo.save(state)
        chat_client.send_message(
            space_id,
            "Désolé, j'ai un souci pour traiter ta réponse. Réessaie dans un instant.",
        )
        return
    result = apply_action(state, action)
    result = _apply_side_effects(result, repo, chat_client)
    repo.save(result.state)
    chat_client.send_message(result.state.space_id, result.message_to_user)

    if result.webhook_now:
        _finish(result.state, repo)


def _route_new_conversation(
    space_id: str,
    text: str,
    sender: dict[str, Any],
    repo: ConversationRepo,
    chat_client,
) -> None:
    """Cas A/B : aucune session active sur ce canal, le routeur décide."""
    if sender.get("type") == "BOT":
        return

    processes = get_process_registry()
    try:
        route = decide_route(text, processes)
    except Exception:
        logger.exception("router_failed", extra={"space_id": space_id})
        chat_client.send_message(
            space_id,
            "Désolé, j'ai un souci pour comprendre ta demande. Réessaie dans un instant.",
        )
        return

    if route.action == "search_knowledge_base":
        try:
            result = answer_from_knowledge_base(route.query or text)
        except Exception:
            logger.exception("kb_answer_crashed", extra={"space_id": space_id})
            chat_client.send_message(
                space_id, "Je n'arrive pas à consulter les documents pour le moment, réessaie dans un instant."
            )
            return
        chat_client.send_message(
            space_id,
            result.text,
            cards=build_rag_cards(result.sources) if result.sources else None,
        )
        return

    if route.action == "clarify_needed":
        chat_client.send_message(space_id, route.message_to_user)
        return

    definition = next((proc for proc in processes if proc.process_id == route.process_id), None)
    if definition is None:
        logger.warning(
            "router_unknown_process", extra={"space_id": space_id, "process_id": route.process_id}
        )
        chat_client.send_message(
            space_id,
            "Je n'ai pas reconnu ce traitement, peux-tu reformuler ?",
        )
        return

    webhook_url = definition.form_spec.default_webhook_url
    if not webhook_url:
        logger.warning("process_no_default_webhook", extra={"process_id": definition.process_id})
        chat_client.send_message(
            space_id,
            "Ce traitement n'est pas encore activable directement depuis le chat. "
            "Demande à quelqu'un de le déclencher autrement.",
        )
        return

    email = resolve_sender_email(sender)
    if not email:
        logger.warning("router_sender_email_unresolved", extra={"space_id": space_id})
        chat_client.send_message(
            space_id,
            "Je n'arrive pas à retrouver ton adresse e-mail pour démarrer ce formulaire. "
            "Peux-tu réessayer plus tard, ou demander à quelqu'un de le déclencher pour toi ?",
        )
        return

    contact = Contact(
        user_email=email,
        display_name=sender.get("displayName"),
        user_id=sender.get("name"),
    )
    try:
        resume_in_space(
            space_id=space_id,
            contact=contact,
            form_spec=definition.form_spec,
            webhook_url=webhook_url,
            repo=repo,
            chat_client=chat_client,
        )
    except ConversationAlreadyActive:
        logger.info("route_already_active", extra={"space_id": space_id})


def _apply_side_effects(result, repo: ConversationRepo, chat_client):
    if result.start_replacement is not None:
        try:
            begin_conversation(
                contact=result.start_replacement,
                form_spec=result.state.form_spec,
                webhook_url=result.state.webhook_url,
                repo=repo,
                chat_client=chat_client,
                webhook_secret=result.state.webhook_secret,
                # La phase interlocuteur précède le questionnaire : à ce
                # stade, state.answers ne contient que d'éventuels
                # field_values d'origine, à reporter sur le remplaçant.
                field_values=dict(result.state.answers),
            )
        except ChatApiError:
            logger.exception(
                "replacement_dm_failed",
                extra={"email": result.start_replacement.user_email},
            )
            result.abandon = False
            result.state.status = "in_progress"
            result.state.phase = "awaiting_replacement"
            result.message_to_user = (
                f"Je n'arrive pas à ouvrir un chat avec {result.start_replacement.user_email}. "
                "Peux-tu me donner un autre e-mail, ou dire si tu ne sais pas qui contacter ?"
            )
            return result
        except ConversationAlreadyActive:
            logger.info(
                "replacement_already_active",
                extra={"email": result.start_replacement.user_email},
            )
            result.abandon = False
            result.state.status = "in_progress"
            result.state.phase = "awaiting_replacement"
            result.message_to_user = (
                f"{result.start_replacement.user_email} a déjà un formulaire en cours avec moi. "
                "Peux-tu me donner un autre e-mail, ou dire si tu ne sais pas qui contacter ?"
            )
            return result

    if result.escalate_to_email and result.escalate_message:
        try:
            escalate_space = chat_client.create_dm(result.escalate_to_email)
            chat_client.send_message(escalate_space, result.escalate_message)
        except ChatApiError:
            logger.exception(
                "escalation_dm_failed",
                extra={"email": result.escalate_to_email},
            )

    if result.abandon:
        result.state.status = "abandoned"
        result.state.current_field_id = None

    return result


def _finish(state: ConversationState, repo: ConversationRepo) -> None:
    ok = deliver_completion(state)
    state.status = "completed" if ok else "failed"
    repo.save(state)
    logger.info(
        "form_finished",
        extra={"space_id": state.space_id, "form_id": state.form_id, "status": state.status},
    )
