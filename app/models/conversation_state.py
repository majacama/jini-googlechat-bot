from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.form_spec import Contact, FormSpec


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class HistoryTurn(BaseModel):
    role: Literal["agent", "user"]
    field_id: str | None = None
    text: str
    ts: str = Field(default_factory=utc_now_iso)


class AgentAction(BaseModel):
    action: Literal["ask", "confirm_value", "reformulate", "complete", "clarify_needed"]
    field_id: str | None = None
    extracted_value: Any | None = None
    message_to_user: str


class ConversationState(BaseModel):
    space_id: str
    form_id: str
    status: Literal["in_progress", "completed", "abandoned", "failed"] = "in_progress"
    contact: Contact
    form_spec: FormSpec
    target_schema: dict[str, Any]
    webhook_url: str
    webhook_secret: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    skipped_field_ids: list[str] = Field(default_factory=list)
    current_field_id: str | None = None
    current_attempt_count: int = 0
    history: list[HistoryTurn] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    completed_at: str | None = None

    def recent_history(self, limit: int = 20) -> list[HistoryTurn]:
        return self.history[-limit:]
