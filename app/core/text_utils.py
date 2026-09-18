import json
import re
from typing import Any

from app.models.form_spec import FieldSpec

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
YES_RE = re.compile(
    r"\b(oui|ouais|yes|yep|ok|okay|exactement|absolument|"
    r"c[' ]?est (bien )?moi|je suis (la bonne personne|responsable)|"
    r"tout à fait|bien sûr)\b",
    re.IGNORECASE,
)
NO_RE = re.compile(
    r"\b(non|nope|\bno\b|pas moi|pas la bonne|mauvaise personne)\b",
    re.IGNORECASE,
)
UNKNOWN_RE = re.compile(
    r"je (ne )?(sais|connais) pas|aucune idée|pas d[' ]idée|"
    r"pas de (nom|prénom|mail|e-?mail|personne)|inconnu|aucune idée",
    re.IGNORECASE,
)
SKIP_RE = re.compile(
    r"^\s*(non|non merci|aucun|aucune|rien|skip|n/?a|nope|no|"
    r"pas d[' ]externe|laisse vide|vide|aucun e-?mail)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def extract_emails(text: str) -> list[str]:
    return [match.group(0) for match in EMAIL_RE.finditer(text or "")]


def is_affirmative(text: str) -> bool:
    return bool(YES_RE.search(text or "")) and not is_negative(text)


def is_negative(text: str) -> bool:
    return bool(NO_RE.search(text or ""))


def is_unknown(text: str) -> bool:
    return bool(UNKNOWN_RE.search(text or ""))


def is_skip_intent(text: str) -> bool:
    return bool(SKIP_RE.match((text or "").strip()))


def extract_replacement(text: str) -> tuple[str | None, str | None]:
    emails = extract_emails(text)
    email = emails[0] if emails else None
    leftover = EMAIL_RE.sub(" ", text or "")
    leftover = re.sub(
        r"\b(prénom|prenom|nom|e-?mail|mail|contacte|contacter|c'est|"
        r"personne|collègue|collegue|voici|svp|please|non|oui|ouais|"
        r"pas de souci|peux-tu|indique|indiquer)\b",
        " ",
        leftover,
        flags=re.IGNORECASE,
    )
    name = " ".join(leftover.split()).strip(" ,;:.-") or None
    return name, email


def render_template(template: str, values: dict[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def schema_allows_array(schema: dict[str, Any] | None) -> bool:
    return "array" in _schema_types(schema or {})


def schema_const_match(schema: dict[str, Any], value: str) -> str | None:
    needle = value.strip().lower()
    for const in _schema_consts(schema):
        if str(const).strip().lower() == needle:
            return const if isinstance(const, str) else str(const)
    return None


def coerce_extracted_value(field: FieldSpec, value: Any) -> Any:
    if value is None:
        return None
    schema = field.json_schema or {}
    if isinstance(value, str):
        text = value.strip()
        const = schema_const_match(schema, text)
        if const is not None:
            return const
        if (text.startswith("[") and text.endswith("]")) or (
            text.startswith("{") and text.endswith("}")
        ):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                pass
        else:
            enums = _schema_enums(schema)
            for option in enums:
                if str(option).strip().lower() == text.lower():
                    return option
            if schema_allows_array(schema):
                emails = extract_emails(text)
                if emails:
                    return emails
                parts = [part.strip() for part in re.split(r"[,;\n]+", text) if part.strip()]
                if len(parts) > 1:
                    return parts
    return value


def _schema_types(schema: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    raw = schema.get("type")
    if isinstance(raw, str):
        types.add(raw)
    elif isinstance(raw, list):
        types.update(str(item) for item in raw)
    for key in ("anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            if isinstance(sub, dict):
                types.update(_schema_types(sub))
    return types


def _schema_consts(schema: dict[str, Any]) -> list[Any]:
    found: list[Any] = []
    if "const" in schema:
        found.append(schema["const"])
    for key in ("anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            if isinstance(sub, dict):
                found.extend(_schema_consts(sub))
    return found


def _schema_enums(schema: dict[str, Any]) -> list[Any]:
    found: list[Any] = []
    if "enum" in schema and isinstance(schema["enum"], list):
        found.extend(schema["enum"])
    for key in ("anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            if isinstance(sub, dict):
                found.extend(_schema_enums(sub))
    return found
