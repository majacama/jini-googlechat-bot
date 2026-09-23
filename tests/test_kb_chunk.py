from app.kb.chunk import chunk_text


def test_empty_text_gives_no_chunk() -> None:
    assert chunk_text("") == []
    assert chunk_text("  \n\n  ") == []


def test_short_text_is_a_single_chunk() -> None:
    chunks = chunk_text("Un court paragraphe.")
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].content == "Un court paragraphe."


def test_long_text_is_split_with_overlap_and_bounded_size() -> None:
    paragraphs = [f"Paragraphe numéro {i}. " + "mot " * 120 for i in range(12)]
    chunks = chunk_text("\n\n".join(paragraphs), max_chars=1000, overlap=200)
    assert len(chunks) > 3
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # taille bornée : max + chevauchement + séparateur
    assert all(len(c.content) <= 1000 + 200 + 2 for c in chunks)
    # chevauchement : la fin d'un morceau se retrouve au début du suivant
    tail = chunks[0].content[-60:]
    assert tail.split()[-1] in chunks[1].content[:300]


def test_section_and_page_metadata() -> None:
    text = "# Introduction\n\nTexte de l'intro.\n\n[page 3]\nContenu de la page trois."
    chunks = chunk_text(text)
    assert chunks[0].metadata["section"] == "Introduction"

    pdf_like = "[page 1]\nPremière page.\n\n[page 2]\n" + "Deuxième page. " * 300
    pages = [c.metadata.get("page") for c in chunk_text(pdf_like, max_chars=800, overlap=100)]
    assert pages[0] == 1
    assert 2 in pages


def test_heading_starts_a_new_chunk_when_current_is_half_full() -> None:
    body = "Un paragraphe assez long. " * 30
    text = f"# Partie A\n\n{body}\n\n# Partie B\n\nSuite."
    chunks = chunk_text(text, max_chars=1000, overlap=0)
    assert len(chunks) == 2
    assert chunks[1].metadata["section"] == "Partie B"


def test_single_huge_block_without_paragraphs_is_still_cut() -> None:
    chunks = chunk_text("Une phrase. " * 900, max_chars=1000, overlap=100)
    assert len(chunks) > 5
    assert all(len(c.content) <= 1000 + 100 + 2 for c in chunks)
