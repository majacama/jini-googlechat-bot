from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def parse_drive_time(value: str | None) -> datetime | None:
    """Drive renvoie du RFC 3339 ('2026-09-14T15:31:53.123Z')."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    path: str  # chemin complet dans le Drive partagé, ex. "Engie/Budget.pdf"
    modified_time: str
    web_link: str
    md5: str | None = None
    size: int | None = None

    @property
    def folder_path(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


@dataclass
class IndexedDoc:
    """Ce que la base sait déjà d'un fichier."""

    file_id: str
    name: str
    folder_path: str
    modified_time: datetime | None
    content_hash: str | None
    status: str  # indexed | skipped | error


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


@dataclass
class KbHit:
    """Un morceau retrouvé par la recherche vectorielle."""

    file_id: str
    name: str
    link: str
    chunk_index: int
    content: str
    similarity: float


@dataclass
class SyncStats:
    seen: int = 0
    indexed: int = 0
    unchanged: int = 0
    touched: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    chunks_written: int = 0
