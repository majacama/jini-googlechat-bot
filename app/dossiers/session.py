"""Conversation « dossier client » d'un espace (DM), gardée dans Firestore.

L'historique garde les contenus Gemini tels quels (appels de tools compris), pour que la
conversation reprenne au message suivant. Une conversation sans activité depuis deux
jours est considérée comme terminée.
"""

import time
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings

SESSION_TTL_SECONDS = 2 * 24 * 3600
COLLECTION = "dossier_sessions"


class PendingConfirmation(BaseModel):
    """Appel de tool qui crée une demande : exécuté seulement après le clic « Confirmer »."""

    name: str
    args: dict[str, Any]
    call_id: str | None = None


class DossierSession(BaseModel):
    space_id: str
    user_email: str
    contents: list[dict[str, Any]] = Field(default_factory=list)
    pending: PendingConfirmation | None = None
    solicitation_id: str | None = None
    solicitation_context: str | None = None
    active: bool = True
    updated_at: float = Field(default_factory=time.time)

    def is_live(self) -> bool:
        return self.active and time.time() - self.updated_at < SESSION_TTL_SECONDS


def _doc_id(space_id: str) -> str:
    return space_id.replace("/", "__")


class MemoryDossierStore:
    def __init__(self) -> None:
        self._items: dict[str, DossierSession] = {}

    def get(self, space_id: str) -> DossierSession | None:
        item = self._items.get(space_id)
        return item if item and item.is_live() else None

    def save(self, session: DossierSession) -> None:
        session.updated_at = time.time()
        self._items[session.space_id] = session


class FirestoreDossierStore:
    def __init__(self, client=None) -> None:
        self._client = client

    def _ref(self, space_id: str):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=get_settings().gcp_project or None)
        return self._client.collection(COLLECTION).document(_doc_id(space_id))

    def get(self, space_id: str) -> DossierSession | None:
        from app.storage.firestore_repo import from_firestore

        snapshot = self._ref(space_id).get()
        if not snapshot.exists:
            return None
        session = DossierSession.model_validate(from_firestore(snapshot.to_dict()))
        return session if session.is_live() else None

    def save(self, session: DossierSession) -> None:
        from app.storage.firestore_repo import to_firestore

        session.updated_at = time.time()
        self._ref(session.space_id).set(to_firestore(session.model_dump(mode="json")))
