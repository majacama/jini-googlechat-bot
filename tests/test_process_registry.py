from app.core.process_registry import load_process_registry


def test_registry_lists_only_forms_with_trigger_intent() -> None:
    definitions = load_process_registry()
    process_ids = {d.process_id for d in definitions}
    # Les dossiers clients passent par le serveur MCP admin.jin.fr, plus par ce formulaire.
    assert "nouveau-dossier-client-v1" not in process_ids
    assert "exemple-v1" not in process_ids  # pas de trigger_intent


def test_registry_skips_invalid_json(tmp_path) -> None:
    (tmp_path / "broken.json").write_text("{ not valid json", encoding="utf-8")
    assert load_process_registry(tmp_path) == []
