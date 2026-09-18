from app.core.text_utils import resolve_placeholders


def test_resolve_placeholders_fills_known_value() -> None:
    text = "Confirmes-tu qu'il faut créer un nouveau dossier client {{nom_dossier}} dans le Drive ?"
    result = resolve_placeholders(text, {"nom_dossier": "_sephora"})
    assert result == "Confirmes-tu qu'il faut créer un nouveau dossier client _sephora dans le Drive ?"


def test_resolve_placeholders_blanks_unknown_value() -> None:
    text = "Confirmes-tu qu'il faut créer un nouveau dossier client {{nom_dossier}} dans le Drive ?"
    result = resolve_placeholders(text, {})
    assert result == "Confirmes-tu qu'il faut créer un nouveau dossier client  dans le Drive ?"


def test_resolve_placeholders_joins_list_values() -> None:
    text = "Équipe : {{equipe_jinners}}"
    result = resolve_placeholders(text, {"equipe_jinners": ["a@jin.fr", "b@jin.fr"]})
    assert result == "Équipe : a@jin.fr, b@jin.fr"


def test_resolve_placeholders_leaves_text_without_placeholders_untouched() -> None:
    assert resolve_placeholders("Rien à remplacer ici.", {"x": "y"}) == "Rien à remplacer ici."
