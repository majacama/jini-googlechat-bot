from typing import Protocol

from app.models.conversation_state import ConversationState


class ConversationRepo(Protocol):
    def get(self, space_id: str) -> ConversationState | None:
        """Session active du canal (`active_session_id`), ou None si le canal
        est libre (aucun formulaire en cours)."""
        ...

    def get_session(self, space_id: str, session_id: str) -> ConversationState | None:
        """Une session précise, active ou terminée (historique)."""
        ...

    def save(self, state: ConversationState) -> None:
        """Enregistre la session et met à jour le pointeur `active_session_id`
        du canal : posé tant que `status == 'in_progress'`, libéré sinon."""
        ...
