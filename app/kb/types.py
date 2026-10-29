from dataclasses import dataclass


@dataclass
class KbHit:
    """Un document source d'une réponse de la base de connaissances."""

    file_id: str
    name: str
    link: str
    chunk_index: int
    content: str
    similarity: float
