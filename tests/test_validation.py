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
