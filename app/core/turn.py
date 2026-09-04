import logging

from app.core.llm import decide_next_action
from app.core.state_machine import (
    apply_action,
    opening_message,
    record_agent_message,
    record_user_message,
)
from app.core.webhook import deliver_completion
from app.models.conversation_state import ConversationState
from app.storage.base import ConversationRepo

logger = logging.getLogger(__name__)


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
    action = decide_next_action(state.form_spec, state, text)
    result = apply_action(state, action)
    repo.save(result.state)
    chat_client.send_message(result.state.space_id, result.message_to_user)

    if result.webhook_now:
        _finish(result.state, repo)


def _finish(state: ConversationState, repo: ConversationRepo) -> None:
    ok = deliver_completion(state)
    state.status = "completed" if ok else "failed"
    repo.save(state)
    logger.info(
        "form_finished",
        extra={"space_id": state.space_id, "form_id": state.form_id, "status": state.status},
    )
