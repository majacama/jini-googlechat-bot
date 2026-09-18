from typing import Literal

from pydantic import BaseModel


class RouteAction(BaseModel):
    action: Literal["search_knowledge_base", "start_process", "clarify_needed"]
    process_id: str | None = None
    query: str | None = None
    message_to_user: str
