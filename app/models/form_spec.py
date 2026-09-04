from typing import Any

from pydantic import BaseModel, Field, field_validator


class Contact(BaseModel):
    user_email: str
    display_name: str | None = None
    user_id: str | None = None


class FieldSpec(BaseModel):
    id: str
    required: bool = True
    max_attempts: int = 3
    json_schema: dict[str, Any]
    question_hint: str
    constraints: str = ""
    format_advice: str = ""
    examples: list[Any] = Field(default_factory=list)

    @field_validator("max_attempts")
    @classmethod
    def max_attempts_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts doit être >= 1")
        return value


class FormSpec(BaseModel):
    form_id: str
    title: str
    language: str = "fr"
    intro_message: str
    global_instructions: str = ""
    fields: list[FieldSpec]

    @field_validator("fields")
    @classmethod
    def unique_field_ids(cls, fields: list[FieldSpec]) -> list[FieldSpec]:
        ids = [field.id for field in fields]
        if len(ids) != len(set(ids)):
            raise ValueError("Les field.id doivent être uniques")
        if not fields:
            raise ValueError("Au moins un champ est requis")
        return fields

    def field_by_id(self, field_id: str) -> FieldSpec | None:
        return next((field for field in self.fields if field.id == field_id), None)

    def next_pending_field(
        self, answers: dict[str, Any], skipped_field_ids: list[str] | None = None
    ) -> FieldSpec | None:
        skipped = set(skipped_field_ids or [])
        for field in self.fields:
            if field.id not in answers and field.id not in skipped:
                return field
        return None


def derive_target_schema(form_spec: FormSpec) -> dict[str, Any]:
    properties = {field.id: field.json_schema for field in form_spec.fields}
    required = [field.id for field in form_spec.fields if field.required]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
