"""Embeddings via Vertex AI (Gemini), dans la région du projet : les textes ne sortent pas de Google Cloud."""

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    model: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def normalize(vector: list[float]) -> list[float]:
    """Normalisation L2. Nécessaire : les vecteurs gemini-embedding-001 réduits (dimension < 3072)
    ne sont pas normalisés, or on compare en distance cosinus."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class VertexEmbedder:
    def __init__(self, model: str, dim: int, project: str, location: str, workers: int = 6) -> None:
        self.model = model
        self._dim = dim
        self._project = project
        self._location = location
        self._workers = workers
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(vertexai=True, project=self._project or None, location=self._location)
        return self._client

    def _embed_one(self, text: str, task_type: str) -> list[float]:
        from google.genai import types

        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = self._get_client().models.embed_content(
                    model=self.model,
                    contents=text,
                    config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=self._dim),
                )
                values = list(response.embeddings[0].values)
                return normalize(values) if self._dim < 3072 else values
            except Exception as exc:  # quota (429), indisponibilité momentanée...
                last_error = exc
                message = str(exc)
                if not any(code in message for code in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500")):
                    raise
                delay = 2**attempt
                logger.warning("embedding_retry", extra={"attempt": attempt + 1, "delay": delay})
                time.sleep(delay)
        raise RuntimeError(f"embedding impossible après plusieurs essais : {last_error}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            return list(pool.map(lambda text: self._embed_one(text, "RETRIEVAL_DOCUMENT"), texts))

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text, "RETRIEVAL_QUERY")
