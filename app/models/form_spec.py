from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class IgnoreExtras(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Contact(BaseModel):
    user_email: str
    display_name: str | None = None
    user_id: str | None = None


class Recipient(IgnoreExtras):
    name: str | None = None
    email: str
    user_id: str | None = None


class InterlocutorYes(IgnoreExtras):
    ack: str = "Parfait, on enchaîne."


class InterlocutorNo(IgnoreExtras):
    ask_for_replacement: str
    action: str = "start_conversation_with_replacement"


class InterlocutorUnknown(IgnoreExtras):
    ack: str
    escalate_to_chat_email: str = ""
    escalation_message: str = ""


class InterlocutorValidation(IgnoreExtras):
    enabled: bool = True
    question: str
    if_yes: InterlocutorYes = Field(default_factory=InterlocutorYes)
    if_no: InterlocutorNo | None = None
    if_unknown: InterlocutorUnknown | None = None


class FieldSpec(IgnoreExtras):
    id: str
    required: bool = True
    max_attempts: int = 3
    json_schema: dict[str, Any]
    question_hint: str = Field(validation_alias=AliasChoices("question_hint", "question"))
    constraints: str = Field(
        default="",
        validation_alias=AliasChoices("constraints", "consignes"),
    )
    format_advice: str = Field(
        default="",
        validation_alias=AliasChoices("format_advice", "format_attendu"),
    )
    examples: list[Any] = Field(
        default_factory=list,
        validation_alias=AliasChoices("examples", "exemples"),
    )
    stop_values: dict[str, str] = Field(default_factory=dict)

    @field_validator("max_attempts")
    @classmethod
    def max_attempts_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts doit être >= 1")
        return value


class FormSpec(IgnoreExtras):
    form_id: str
    title: str
    language: str = "fr"
    intro_message: str = ""
    global_instructions: str = ""
    recipient: Recipient | None = None
    interlocutor_validation: InterlocutorValidation | None = None
    fields: list[FieldSpec]

    @model_validator(mode="before")
    @classmethod
    def flatten_conversation_spec(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        introduction = data.get("introduction")
        if isinstance(introduction, dict) and not data.get("intro_message"):
            data["intro_message"] = introduction.get("message") or ""
        tone = data.get("tone")
        if isinstance(tone, dict) and not data.get("global_instructions"):
            data["global_instructions"] = tone.get("instructions") or ""
        questionnaire = data.get("questionnaire")
        if isinstance(questionnaire, dict) and "fields" not in data:
            data["fields"] = questionnaire.get("fields") or []
        return data

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

    def uses_interlocutor_gate(self) -> bool:
        return bool(self.interlocutor_validation and self.interlocutor_validation.enabled)


def derive_target_schema(form_spec: FormSpec) -> dict[str, Any]:
    properties = {field.id: field.json_schema for field in form_spec.fields}
    required = [field.id for field in form_spec.fields if field.required]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
