from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.models.form_spec import FieldSpec


@dataclass
class ValidationResult:
    ok: bool
    value: Any | None = None
    error: str | None = None


def validate_field(field: FieldSpec, value: Any) -> ValidationResult:
    validator = Draft202012Validator(
        field.json_schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    try:
        validator.validate(value)
    except ValidationError as exc:
        return ValidationResult(ok=False, value=value, error=exc.message)
    return ValidationResult(ok=True, value=value)


def required_fields_complete(form_spec, answers: dict[str, Any]) -> bool:
    return all(field.id in answers for field in form_spec.fields if field.required)
