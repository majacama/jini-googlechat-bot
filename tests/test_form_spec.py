import json
from pathlib import Path

from app.models.form_spec import FormSpec

FORMS = Path(__file__).resolve().parent.parent / "forms"


def test_loads_nouveau_dossier_client_json() -> None:
    data = json.loads((FORMS / "nouveau-dossier-client.json").read_text(encoding="utf-8"))
    spec = FormSpec.model_validate(data)
    assert spec.form_id == "nouveau-dossier-client-v1"
    assert spec.intro_message.startswith("Bonjour, je suis Jin Investigator Agent")
    assert "Tutoiement" in spec.global_instructions
    assert spec.recipient is not None
    assert spec.recipient.email == "fdiaz@jin.fr"
    assert spec.recipient.user_id is None
    assert spec.uses_interlocutor_gate()
    nom = spec.field_by_id("nom_dossier")
    assert nom is not None
    assert "{{nom_dossier}}" in nom.question_hint
    assert "underscore" in nom.constraints
    assert nom.format_advice.startswith("Chaîne minuscule")
    assert "_sephora" in nom.examples
    assert nom.json_schema["pattern"] == "^_[a-z0-9]+(?:-[a-z0-9]+)*$"
    creation = spec.field_by_id("creation_dossier")
    assert creation is not None
    assert creation.stop_values.get("non")
    assert [field.id for field in spec.fields] == [
        "creation_dossier",
        "nom_dossier",
        "niveau_securite",
        "equipe_jinners",
        "externes",
        "membres_externes_chat",
        "presales_folder_url",
    ]


def test_loads_exemple_template_json() -> None:
    data = json.loads((FORMS / "exemple-a-remplir.json").read_text(encoding="utf-8"))
    spec = FormSpec.model_validate(data)
    assert spec.field_by_id("nom_fournisseur") is not None
    assert spec.intro_message
