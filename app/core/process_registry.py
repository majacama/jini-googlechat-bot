import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.models.form_spec import FormSpec

logger = logging.getLogger(__name__)

FORMS_DIR = Path(__file__).resolve().parent.parent.parent / "forms"


@dataclass
class ProcessDefinition:
    process_id: str
    trigger_intent: str
    form_spec: FormSpec


def load_process_registry(forms_dir: Path | None = None) -> list[ProcessDefinition]:
    """Scanne forms/*.json et ne retient que les formulaires déclenchables
    depuis le chat (ceux qui déclarent trigger_intent)."""
    directory = forms_dir or FORMS_DIR
    definitions: list[ProcessDefinition] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            spec = FormSpec.model_validate(data)
        except Exception:
            logger.warning("process_registry_invalid_form", extra={"file": str(path)})
            continue
        if not spec.trigger_intent:
            continue
        definitions.append(
            ProcessDefinition(
                process_id=spec.form_id,
                trigger_intent=spec.trigger_intent,
                form_spec=spec,
            )
        )
    return definitions


@lru_cache
def get_process_registry() -> list[ProcessDefinition]:
    return load_process_registry()
