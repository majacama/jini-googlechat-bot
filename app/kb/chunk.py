"""Découpage du texte extrait en morceaux pour la recherche vectorielle."""

import re

from app.kb.types import Chunk

MAX_CHARS = 2200  # environ 500 à 600 tokens
OVERLAP_CHARS = 250

_PAGE_RE = re.compile(r"^\[page (\d+)\]\n?")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n")


def _split_long(text: str, max_chars: int) -> list[str]:
    """Découpe un bloc trop long sur les fins de phrase, sinon à largeur fixe."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, size: int) -> str:
    """Fin du texte sur `size` caractères environ, sans couper un mot."""
    if len(text) <= size:
        return text
    cut = text[-size:]
    space = cut.find(" ")
    return cut[space + 1 :] if 0 <= space < len(cut) - 1 else cut


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[Chunk]:
    # 1. Blocs annotés (texte, section courante, page courante)
    units: list[tuple[str, bool, str | None, int | None]] = []
    section: str | None = None
    page: int | None = None
    for raw in re.split(r"\n{2,}", text):
        block = raw.strip()
        if not block:
            continue
        page_match = _PAGE_RE.match(block)
        if page_match:
            page = int(page_match.group(1))
            block = block[page_match.end() :].strip()
            if not block:
                continue
        is_heading = block.startswith("#")
        if is_heading:
            section = block.lstrip("#").strip().split("\n", 1)[0]
        for piece in _split_long(block, max_chars) if len(block) > max_chars else [block]:
            units.append((piece, is_heading, section, page))

    # 2. Regroupement en morceaux
    chunks: list[Chunk] = []
    buffer: list[str] = []
    length = 0
    real = 0  # nombre de blocs « réels » (hors texte de chevauchement repris du morceau précédent)
    meta_section: str | None = None
    meta_page: int | None = None

    def flush() -> str:
        content = "\n\n".join(buffer).strip()
        if content:
            meta: dict[str, object] = {}
            if meta_section:
                meta["section"] = meta_section
            if meta_page is not None:
                meta["page"] = meta_page
            chunks.append(
                Chunk(index=len(chunks), content=content, token_count=max(1, len(content) // 4), metadata=meta)
            )
        return content

    for piece, is_heading, sec, pg in units:
        too_big = length + 2 + len(piece) > max_chars
        new_section = is_heading and length >= max_chars // 2
        if real and (too_big or new_section):
            previous = flush()
            carried = _tail(previous, overlap) if overlap else ""
            buffer, length, real = ([carried], len(carried), 0) if carried else ([], 0, 0)
        if real == 0:
            meta_section, meta_page = sec, pg
        buffer.append(piece)
        length += len(piece) + (2 if len(buffer) > 1 else 0)
        real += 1

    if real:
        flush()
    return chunks
