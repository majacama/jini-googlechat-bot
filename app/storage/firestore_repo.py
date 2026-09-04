from app.config import get_settings
from app.models.conversation_state import ConversationState


def document_id_from_space(space_id: str) -> str:
    return space_id.replace("/", "__")


class FirestoreConversationRepo:
    def __init__(self, client=None, collection: str | None = None) -> None:
        self._client = client
        self._collection_name = collection

    def _collection(self):
        if self._client is None:
            from google.cloud import firestore

            settings = get_settings()
            self._client = firestore.Client(project=settings.gcp_project or None)
            self._collection_name = settings.firestore_collection
        return self._client.collection(self._collection_name)

    def get(self, space_id: str) -> ConversationState | None:
        snapshot = self._collection().document(document_id_from_space(space_id)).get()
        if not snapshot.exists:
            return None
        return ConversationState.model_validate(snapshot.to_dict())

    def save(self, state: ConversationState) -> None:
        self._collection().document(document_id_from_space(state.space_id)).set(
            state.model_dump()
        )
