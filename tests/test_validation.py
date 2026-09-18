import json
from pathlib import Path

from app.core.validation import required_fields_complete, validate_field
from app.models.form_spec import FormSpec


def test_string_min_length(form_spec: FormSpec) -> None:
    field = form_spec.field_by_id("nom_fournisseur")
    assert field is not None
    assert validate_field(field, "Acme SAS").ok
    assert not validate_field(field, "A").ok


def test_date_format(form_spec: FormSpec) -> None:
    field = form_spec.field_by_id("date_debut")
    assert field is not None
    assert validate_field(field, "2026-03-15").ok
    assert not validate_field(field, "15/03/2026").ok


def test_required_fields_complete(form_spec: FormSpec) -> None:
    assert not required_fields_complete(form_spec, {})
    assert required_fields_complete(
        form_spec,
        {"nom_fournisseur": "Acme SAS", "date_debut": "2026-03-15"},
    )


def test_email_list_and_idem_externes() -> None:
    data = json.loads(
        (Path(__file__).resolve().parent.parent / "forms" / "nouveau-dossier-client.json").read_text(
            encoding="utf-8"
        )
    )
    spec = FormSpec.model_validate(data)
    equipe = spec.field_by_id("equipe_jinners")
    assert equipe is not None
    assert validate_field(equipe, "marie.martin@jin.fr, paul.durand@jin.fr").ok
    membres = spec.field_by_id("membres_externes_chat")
    assert membres is not None
    assert not validate_field(membres, "idem externes").ok
    assert validate_field(membres, ["partner@agence.com"]).ok
    nom = spec.field_by_id("nom_dossier")
    assert nom is not None
    assert validate_field(nom, "_moulin-de-valdonne").ok
    assert not validate_field(nom, "Sephora").ok
