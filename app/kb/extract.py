"""Extraction du texte des fichiers du Drive.

Sortie en texte brut avec quelques repères que le découpage exploite :
  - une ligne commençant par '#' = titre de section ;
  - une ligne '[page N]' = repère de page (PDF).
"""

import io
import re

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

MIN_PDF_CHARS = 200  # en dessous, on considère le PDF comme scanné / sans texte
MAX_SHEET_ROWS = 2000


class ExtractionError(RuntimeError):
    """Le fichier ne donne pas de texte exploitable (à ne pas retenter tant qu'il ne change pas)."""


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _from_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _from_docx(data: bytes) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    lines: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            style = (block.style.name or "") if block.style is not None else ""
            match = re.match(r"Heading (\d)", style)
            if style == "Title":
                lines.append(f"# {text}")
            elif match:
                lines.append(f"{'#' * min(int(match.group(1)), 4)} {text}")
            else:
                lines.append(text)
        elif isinstance(block, Table):
            for row in block.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n\n".join(lines)


def _pptx_shape_text(shape) -> list[str]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    out: list[str] = []
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for child in shape.shapes:
            out += _pptx_shape_text(child)
    elif getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                out.append(" | ".join(cells))
    elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = shape.text_frame.text.strip()
        if text:
            out.append(text)
    return out


def _from_pptx(data: bytes) -> str:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    sections: list[str] = []
    for number, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            parts += _pptx_shape_text(shape)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"Notes : {notes}")
        if parts:
            sections.append(f"## Diapositive {number}\n\n" + "\n\n".join(parts))
    return "\n\n".join(sections)


def _from_xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sections: list[str] = []
    for sheet in workbook.worksheets:
        rows: list[str] = []
        for count, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if count > MAX_SHEET_ROWS:
                rows.append(f"(feuille tronquée après {MAX_SHEET_ROWS} lignes)")
                break
            cells = ["" if value is None else str(value).strip() for value in row]
            if any(cells):
                rows.append(" | ".join(cells).rstrip(" |"))
        if rows:
            sections.append(f"## Feuille {sheet.title}\n\n" + "\n".join(rows))
    return "\n\n".join(sections)


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"[page {number}]\n{text}")
    joined = "\n\n".join(pages)
    if len(joined) < MIN_PDF_CHARS:
        raise ExtractionError("PDF sans texte extractible (scanné ?) : à traiter par OCR")
    return joined


_EXTRACTORS = {
    DOCX_MIME: _from_docx,
    PPTX_MIME: _from_pptx,
    XLSX_MIME: _from_xlsx,
    "application/pdf": _from_pdf,
    "text/plain": _from_text,
    "text/markdown": _from_text,
    "text/x-markdown": _from_text,
    "text/csv": _from_text,
}

# Types que le Drive renvoie tels quels ou que l'export Google produit.
_GOOGLE_NATIVE = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.spreadsheet",
}


def is_supported(mime_type: str) -> bool:
    return mime_type in _EXTRACTORS or mime_type in _GOOGLE_NATIVE


def extract_text(data: bytes, mime_type: str) -> str:
    """`mime_type` est le type effectif (celui de l'export pour un fichier Google)."""
    extractor = _EXTRACTORS.get(mime_type)
    if extractor is None:
        raise ExtractionError(f"type non pris en charge : {mime_type}")
    try:
        text = _clean(extractor(data))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"lecture impossible ({type(exc).__name__}: {exc})") from exc
    if not text:
        raise ExtractionError("aucun texte trouvé dans le fichier")
    return text
