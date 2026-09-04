from app.models.conversation_state import ConversationState
from app.storage.firestore_repo import document_id_from_space


class MemoryConversationRepo:
    def __init__(self) -> None:
        self._docs: dict[str, ConversationState] = {}

    def get(self, space_id: str) -> ConversationState | None:
        stored = self._docs.get(document_id_from_space(space_id))
        return stored.model_copy(deep=True) if stored else None

    def save(self, state: ConversationState) -> None:
        self._docs[document_id_from_space(state.space_id)] = state.model_copy(deep=True)
