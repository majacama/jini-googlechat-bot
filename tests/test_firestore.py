from app.storage.firestore_repo import FirestoreConversationRepo, document_id_from_space
from app.models.conversation_state import ConversationState


class _Snapshot:
    def __init__(self, data: dict | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return self._data


class _Document:
    """Mime un DocumentReference Firestore : data propre + sous-collections."""

    def __init__(self, entry: dict) -> None:
        self._entry = entry  # {"data": dict|None, "sub": dict[name, dict[doc_id, entry]]}

    def get(self) -> _Snapshot:
        return _Snapshot(self._entry["data"])

    def set(self, data: dict, merge: bool = False) -> None:
        if merge and self._entry["data"] is not None:
            self._entry["data"] = {**self._entry["data"], **data}
        else:
            self._entry["data"] = data

    def collection(self, name: str) -> "_Collection":
        return _Collection(self._entry["sub"].setdefault(name, {}))


class _Collection:
    def __init__(self, store: dict) -> None:
        self._store = store

    def document(self, doc_id: str) -> _Document:
        entry = self._store.setdefault(doc_id, {"data": None, "sub": {}})
        return _Document(entry)


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def collection(self, _name: str) -> _Collection:
        return _Collection(self.store)


def test_document_id_from_space_replaces_slash() -> None:
    assert document_id_from_space("spaces/hj77AqAAAAE") == "spaces__hj77AqAAAAE"


def test_firestore_repo_roundtrip(conversation: ConversationState) -> None:
    client = _FakeClient()
    repo = FirestoreConversationRepo(client=client, collection="conversations")
    conversation.answers["nom_fournisseur"] = "JIN SA"
    repo.save(conversation)

    loaded = repo.get(conversation.space_id)
    assert loaded is not None
    assert loaded.form_id == conversation.form_id
    assert loaded.answers["nom_fournisseur"] == "JIN SA"
    assert loaded.contact.user_email == "collaborateur@jin.fr"

    doc_id = "spaces__AAAAtest"
    assert doc_id in client.store
    channel_data = client.store[doc_id]["data"]
    assert channel_data["active_session_id"] == conversation.session_id


def test_completed_session_releases_active_pointer(conversation: ConversationState) -> None:
    client = _FakeClient()
    repo = FirestoreConversationRepo(client=client, collection="conversations")
    repo.save(conversation)

    conversation.status = "completed"
    repo.save(conversation)

    assert repo.get(conversation.space_id) is None
    # mais l'historique de la session reste consultable
    archived = repo.get_session(conversation.space_id, conversation.session_id)
    assert archived is not None
    assert archived.status == "completed"


def test_firestore_accepts_nested_example_lists() -> None:
    import json
    from pathlib import Path

    from app.models.form_spec import Contact, FormSpec, derive_target_schema

    data = json.loads(
        (Path(__file__).resolve().parent.parent / "forms" / "nouveau-dossier-client.json").read_text(
            encoding="utf-8"
        )
    )
    spec = FormSpec.model_validate(data)
    spec.fields[0].examples = [["nested", "array"]]
    state = ConversationState(
        space_id="spaces/nested",
        form_id=spec.form_id,
        contact=Contact(user_email="fdiaz@jin.fr"),
        form_spec=spec,
        target_schema=derive_target_schema(spec),
        webhook_url="https://example.test/ingest",
        phase="interlocutor",
    )
    client = _FakeClient()
    repo = FirestoreConversationRepo(client=client, collection="conversations")
    repo.save(state)

    session_doc = client.store["spaces__nested"]["sub"]["sessions"][state.session_id]["data"]
    assert session_doc["form_spec"]["fields"][0]["examples"] == [{"__list__": ["nested", "array"]}]

    loaded = repo.get(state.space_id)
    assert loaded is not None
    assert loaded.form_spec.fields[0].examples == [["nested", "array"]]


def test_firestore_repo_missing_document_returns_none() -> None:
    repo = FirestoreConversationRepo(client=_FakeClient(), collection="conversations")
    assert repo.get("spaces/unknown") is None
