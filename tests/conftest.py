import json
from pathlib import Path

import pytest

from app.models.conversation_state import ConversationState
from app.models.form_spec import Contact, FormSpec, derive_target_schema

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def form_spec() -> FormSpec:
    data = json.loads((FIXTURES / "form_spec_exemple.json").read_text(encoding="utf-8"))
    return FormSpec.model_validate(data)


@pytest.fixture
def conversation(form_spec: FormSpec) -> ConversationState:
    return ConversationState(
        space_id="spaces/AAAAtest",
        form_id=form_spec.form_id,
        contact=Contact(user_email="collaborateur@jin.fr", display_name="Collab"),
        form_spec=form_spec,
        target_schema=derive_target_schema(form_spec),
        webhook_url="https://example.test/ingest",
        current_field_id=form_spec.fields[0].id,
    )
