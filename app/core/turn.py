import logging

from app.core.chat_client import ChatApiError
from app.core.llm import decide_next_action
from app.core.state_machine import (
    apply_action,
    opening_message,
    record_agent_message,
    record_user_message,
)
from app.core.webhook import deliver_completion
from app.models.conversation_state import ConversationState
from app.models.form_spec import Contact, FormSpec, derive_target_schema
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)


def build_initial_state(
    space_id: str,
    contact: Contact,
    form_spec: FormSpec,
    webhook_url: str,
    webhook_secret: str | None = None,
) -> ConversationState:
    use_gate = form_spec.uses_interlocutor_gate()
    return ConversationState(
        space_id=space_id,
        form_id=form_spec.form_id,
        contact=contact,
        form_spec=form_spec,
        target_schema=derive_target_schema(form_spec),
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        phase="interlocutor" if use_gate else "questionnaire",
        current_field_id=None if use_gate else form_spec.fields[0].id,
    )


def begin_conversation(
    contact: Contact,
    form_spec: FormSpec,
    webhook_url: str,
    repo: ConversationRepo,
    chat_client,
    webhook_secret: str | None = None,
) -> ConversationState:
    space_id = chat_client.create_dm(contact.user_id or contact.user_email)
    state = build_initial_state(
        space_id=space_id,
        contact=contact,
        form_spec=form_spec,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
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
) -> None:
    state = repo.get(space_id)
    if state is None:
        logger.warning("unknown_space", extra={"space_id": space_id})
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
