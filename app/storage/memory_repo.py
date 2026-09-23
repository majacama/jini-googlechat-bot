from app.models.conversation_state import ConversationState
from app.storage.firestore_repo import MAX_QA, document_id_from_space, fresh_qa, new_qa


class MemoryConversationRepo:
    def __init__(self) -> None:
        self._active: dict[str, str] = {}  # doc_id -> session_id
        self._sessions: dict[tuple[str, str], ConversationState] = {}
        self._qa: dict[str, list[dict]] = {}

    def get(self, space_id: str) -> ConversationState | None:
        doc_id = document_id_from_space(space_id)
        active_session_id = self._active.get(doc_id)
        if not active_session_id:
            return None
        return self.get_session(space_id, active_session_id)

    def get_session(self, space_id: str, session_id: str) -> ConversationState | None:
        stored = self._sessions.get((document_id_from_space(space_id), session_id))
        return stored.model_copy(deep=True) if stored else None

    def get_recent_qa(self, space_id: str) -> list[dict]:
        return fresh_qa(self._qa.get(document_id_from_space(space_id), []))

    def add_qa(self, space_id: str, question: str, answer: str) -> None:
        doc_id = document_id_from_space(space_id)
        self._qa[doc_id] = [*fresh_qa(self._qa.get(doc_id, [])), new_qa(question, answer)][-MAX_QA:]

    def save(self, state: ConversationState) -> None:
        doc_id = document_id_from_space(state.space_id)
        self._sessions[(doc_id, state.session_id)] = state.model_copy(deep=True)
        if state.status == "in_progress":
            self._active[doc_id] = state.session_id
        elif self._active.get(doc_id) == state.session_id:
            self._active.pop(doc_id, None)
