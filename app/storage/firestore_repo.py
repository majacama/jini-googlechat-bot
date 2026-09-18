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

    def get(self, space_id: str) -> ConversationState | None:
        doc_id = document_id_from_space(space_id)
        snapshot = self._collection().document(doc_id).get()
        if not snapshot.exists:
            return None
        return ConversationState.model_validate(from_firestore(snapshot.to_dict()))

    def save(self, state: ConversationState) -> None:
        doc_id = document_id_from_space(state.space_id)
        self._collection().document(doc_id).set(to_firestore(state.model_dump(mode="json")))
        logger.info(
            "firestore_saved doc_id=%s form_id=%s status=%s field=%s",
            doc_id,
            state.form_id,
            state.status,
            state.current_field_id,
        )
