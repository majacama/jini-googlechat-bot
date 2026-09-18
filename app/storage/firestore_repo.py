import logging
from typing import Any

from app.config import get_settings
from app.models.conversation_state import ConversationState

logger = logging.getLogger(__name__)

NESTED_LIST = "__list__"


def document_id_from_space(space_id: str) -> str:
    return space_id.replace("/", "__")


def to_firestore(value: Any) -> Any:
    """Firestore refuse les tableaux de tableaux ; on les encapsule."""
    if isinstance(value, dict):
        return {str(key): to_firestore(item) for key, item in value.items()}
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        encoded: list[Any] = []
        for item in value:
            converted = to_firestore(item)
            if isinstance(item, (list, tuple)):
                encoded.append({NESTED_LIST: converted})
            else:
                encoded.append(converted)
        return encoded
    return value


def from_firestore(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value.keys()) == {NESTED_LIST}:
            return from_firestore(value[NESTED_LIST])
        return {key: from_firestore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_firestore(item) for item in value]
    return value


SESSIONS_SUBCOLLECTION = "sessions"


class FirestoreConversationRepo:
    def __init__(self, client=None, collection: str | None = None) -> None:
        self._client = client
        self._collection_name = collection

    def _collection(self):
        settings = get_settings()
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=settings.gcp_project or None)
        name = self._collection_name or settings.firestore_collection
        return self._client.collection(name)

    def _channel_ref(self, space_id: str):
        return self._collection().document(document_id_from_space(space_id))

    def get(self, space_id: str) -> ConversationState | None:
        channel = self._channel_ref(space_id).get()
        if not channel.exists:
            return None
        active_session_id = (channel.to_dict() or {}).get("active_session_id")
        if not active_session_id:
            return None
        return self.get_session(space_id, active_session_id)

    def get_session(self, space_id: str, session_id: str) -> ConversationState | None:
        snapshot = self._channel_ref(space_id).collection(SESSIONS_SUBCOLLECTION).document(session_id).get()
        if not snapshot.exists:
            return None
        return ConversationState.model_validate(from_firestore(snapshot.to_dict()))

    def save(self, state: ConversationState) -> None:
        channel_ref = self._channel_ref(state.space_id)
        channel_ref.collection(SESSIONS_SUBCOLLECTION).document(state.session_id).set(
            to_firestore(state.model_dump(mode="json"))
        )

        channel_snapshot = channel_ref.get()
        current_active = (channel_snapshot.to_dict() or {}).get("active_session_id") if channel_snapshot.exists else None
        if state.status == "in_progress":
            new_active = state.session_id
        elif current_active == state.session_id:
            new_active = None
        else:
            new_active = current_active
        channel_ref.set({"active_session_id": new_active, "updated_at": state.updated_at}, merge=True)

        logger.info(
            "firestore_saved space=%s session=%s form_id=%s status=%s field=%s active=%s",
            state.space_id,
            state.session_id,
            state.form_id,
            state.status,
            state.current_field_id,
            new_active,
        )
