from app.kb.answer import KbAnswer, answer_question
from app.kb.types import KbHit


class FakeEmbedder:
    model = "fake"

    def embed_query(self, text):
        return [0.0]


class FakeStore:
    def __init__(self, hits):
        self.hits = hits
        self.args = None

    def search(self, embedding, top_k, min_similarity):
        self.args = (top_k, min_similarity)
        return self.hits


def _hits():
    return [
        KbHit("f1", "PSSI.pdf", "https://d/1", 0, "Le mot de passe expire tous les 90 jours.", 0.8),
        KbHit("f1", "PSSI.pdf", "https://d/1", 1, "Autre passage.", 0.75),
        KbHit("f2", "Charte.docx", "https://d/2", 0, "Charte.", 0.7),
    ]


def test_no_hits_answers_nothing_found_without_calling_llm() -> None:
    def boom(prompt):
        raise AssertionError("pas d'appel LLM sans extrait")

    result = answer_question("q", FakeStore([]), FakeEmbedder(), generate=boom)
    assert not result.found and "rien trouvé" in result.text and result.sources == []


def test_grounded_answer_dedupes_sources_in_model_order() -> None:
    gen = lambda p: {"answerable": True, "answer": "90 jours.", "used_sources": [3, 1, 2]}
    result = answer_question("q", FakeStore(_hits()), FakeEmbedder(), generate=gen)
    assert result.found and result.text == "90 jours."
    assert [s.file_id for s in result.sources] == ["f2", "f1"]


def test_unanswerable_has_no_sources() -> None:
    gen = lambda p: {"answerable": False, "answer": "Aucun document ne le dit.", "used_sources": [1]}
    result = answer_question("q", FakeStore(_hits()), FakeEmbedder(), generate=gen)
    assert not result.found and result.sources == [] and "Aucun document" in result.text


def test_missing_or_invalid_used_sources_fall_back_to_top_documents() -> None:
    gen = lambda p: {"answerable": True, "answer": "ok", "used_sources": [99, "x"]}
    result = answer_question("q", FakeStore(_hits()), FakeEmbedder(), generate=gen)
    assert [s.file_id for s in result.sources] == ["f1", "f2"]


def test_excerpts_are_numbered_in_prompt() -> None:
    seen = {}
    def gen(p):
        seen["p"] = p
        return {"answerable": True, "answer": "ok", "used_sources": [1]}
    answer_question("ma question", FakeStore(_hits()), FakeEmbedder(), generate=gen)
    assert "[1] Document « PSSI.pdf »" in seen["p"] and "ma question" in seen["p"]
