from typing import Protocol

from app.models.conversation_state import ConversationState


class ConversationRepo(Protocol):
    def get(self, space_id: str) -> ConversationState | None: ...

    def save(self, state: ConversationState) -> None: ...
