from app.kb.sync import run_sync
from app.kb.types import Chunk, DriveFile, IndexedDoc, SyncStats, parse_drive_time


class FakeDrive:
    def __init__(self) -> None:
        self.files: list[DriveFile] = []
        self.contents: dict[str, tuple[bytes, str]] = {}
        self.fetched: list[str] = []
        self.fail_on: set[str] = set()

    def put(self, file_id: str, path: str, text: str, modified: str = "2026-09-20T10:00:00.000Z",
            mime: str = "text/plain") -> DriveFile:
        file = DriveFile(id=file_id, name=path.rsplit("/", 1)[-1], mime_type=mime, path=path,
                         modified_time=modified, web_link=f"https://drive.example/{file_id}")
        self.files = [f for f in self.files if f.id != file_id] + [file]
        self.contents[file_id] = (text.encode(), mime)
        return file

    def list_files(self) -> list[DriveFile]:
        return sorted(self.files, key=lambda f: f.path)

    def fetch(self, file: DriveFile) -> tuple[bytes, str]:
        self.fetched.append(file.id)
        if file.id in self.fail_on:
            raise RuntimeError("Drive 500")
        return self.contents[file.id]


class FakeEmbedder:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(t)), 1.0] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, IndexedDoc] = {}
        self.chunks: dict[str, list[Chunk]] = {}
        self.errors: dict[str, str] = {}
        self.writes = 0

    def try_lock(self) -> bool:
        return True

    def unlock(self) -> None:
        pass

    def indexed(self) -> dict[str, IndexedDoc]:
        return dict(self.docs)

    def _put(self, file: DriveFile, status: str, content_hash: str | None) -> None:
        self.writes += 1
        self.docs[file.id] = IndexedDoc(file.id, file.name, file.folder_path,
                                        parse_drive_time(file.modified_time), content_hash, status)

    def save_document(self, file, content_hash, chunks, model) -> None:
        self._put(file, "indexed", content_hash)
        self.chunks[file.id] = chunks

    def touch_document(self, file) -> None:
        old = self.docs[file.id]
        self._put(file, old.status, old.content_hash)

    def mark_document(self, file, status, error) -> None:
        self._put(file, status, None)
        self.chunks.pop(file.id, None)
        self.errors[file.id] = error

    def delete_documents(self, file_ids) -> None:
        self.writes += 1
        for file_id in file_ids:
            self.docs.pop(file_id, None)
            self.chunks.pop(file_id, None)

    def start_run(self) -> int:
        return 1

    def finish_run(self, run_id: int, stats: SyncStats, status: str, error: str | None = None) -> None:
        pass


def _setup() -> tuple[FakeDrive, FakeEmbedder, FakeStore]:
    return FakeDrive(), FakeEmbedder(), FakeStore()


def test_new_file_is_indexed_with_embeddings_and_path_header() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "Engie/note.md", "# Titre\n\nContenu de la note.")
    stats = run_sync(drive, embedder, store)
    assert stats.seen == 1 and stats.indexed == 1 and stats.chunks_written == 1
    assert store.docs["a"].status == "indexed"
    assert store.chunks["a"][0].embedding  # vecteur posé
    # le chemin est joint au texte vectorisé : len("Engie/note.md\n\n" + contenu)
    assert store.chunks["a"][0].embedding[0] == float(len("Engie/note.md\n\n") + len(store.chunks["a"][0].content))


def test_second_run_without_change_does_nothing() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "note.md", "Contenu.")
    run_sync(drive, embedder, store)
    calls, fetched, writes = embedder.calls, len(drive.fetched), store.writes
    stats = run_sync(drive, embedder, store)
    assert stats.unchanged == 1 and stats.indexed == 0
    assert (embedder.calls, len(drive.fetched), store.writes) == (calls, fetched, writes)


def test_modified_content_is_reindexed_and_old_chunks_replaced() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "note.md", "Ancien contenu.")
    run_sync(drive, embedder, store)
    drive.put("a", "note.md", "Nouveau contenu, différent.", modified="2026-09-21T10:00:00.000Z")
    stats = run_sync(drive, embedder, store)
    assert stats.indexed == 1
    assert store.chunks["a"][0].content == "Nouveau contenu, différent."


def test_touched_file_with_same_text_does_not_recompute_embeddings() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "note.md", "Même texte.")
    run_sync(drive, embedder, store)
    calls = embedder.calls
    drive.put("a", "note.md", "Même texte.", modified="2026-09-22T10:00:00.000Z")
    stats = run_sync(drive, embedder, store)
    assert stats.touched == 1 and stats.indexed == 0
    assert embedder.calls == calls
    assert store.docs["a"].modified_time == parse_drive_time("2026-09-22T10:00:00.000Z")


def test_moved_file_updates_metadata_only() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "Engie/note.md", "Contenu.")
    run_sync(drive, embedder, store)
    calls, fetched = embedder.calls, len(drive.fetched)
    drive.put("a", "Archives/note.md", "Contenu.")  # même modifiedTime, autre dossier
    stats = run_sync(drive, embedder, store)
    assert stats.touched == 1
    assert store.docs["a"].folder_path == "Archives"
    assert (embedder.calls, len(drive.fetched)) == (calls, fetched)


def test_file_removed_from_drive_is_deleted() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "a.md", "Un.")
    drive.put("b", "b.md", "Deux.")
    run_sync(drive, embedder, store)
    drive.files = [f for f in drive.files if f.id != "b"]
    stats = run_sync(drive, embedder, store)
    assert stats.deleted == 1
    assert "b" not in store.docs and "a" in store.docs


def test_empty_listing_never_wipes_the_index() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "a.md", "Un.")
    run_sync(drive, embedder, store)
    drive.files = []  # perte d'accès ou erreur d'API, pas un Drive vidé
    stats = run_sync(drive, embedder, store)
    assert stats.deleted == 0
    assert "a" in store.docs


def test_unsupported_type_is_marked_skipped_once() -> None:
    drive, embedder, store = _setup()
    drive.put("img", "photo.png", "x", mime="image/png")
    stats = run_sync(drive, embedder, store)
    assert stats.skipped == 1 and store.docs["img"].status == "skipped"
    again = run_sync(drive, embedder, store)
    assert again.unchanged == 1 and again.skipped == 0  # pas retraité tant qu'il ne change pas


def test_extraction_error_is_skipped_not_failed() -> None:
    drive, embedder, store = _setup()
    drive.put("vide", "vide.md", "   \n  ")
    stats = run_sync(drive, embedder, store)
    assert stats.skipped == 1 and stats.failed == 0
    assert "aucun texte" in store.errors["vide"]


def test_transient_failure_is_recorded_then_retried() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "a.md", "Contenu.")
    drive.fail_on = {"a"}
    stats = run_sync(drive, embedder, store)
    assert stats.failed == 1 and store.docs["a"].status == "error"
    drive.fail_on = set()  # le Drive répond de nouveau
    retry = run_sync(drive, embedder, store)
    assert retry.indexed == 1 and store.docs["a"].status == "indexed"


def test_one_failing_file_does_not_block_the_others() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "a.md", "Un.")
    drive.put("b", "b.md", "Deux.")
    drive.fail_on = {"a"}
    stats = run_sync(drive, embedder, store)
    assert stats.failed == 1 and stats.indexed == 1
    assert store.docs["b"].status == "indexed"


def test_dry_run_writes_nothing_and_computes_no_embedding() -> None:
    drive, embedder, store = _setup()
    drive.put("a", "a.md", "Contenu à valider.")
    stats = run_sync(drive, embedder, store, dry_run=True)
    assert stats.indexed == 1 and stats.chunks_written == 1
    assert store.writes == 0 and embedder.calls == 0 and not store.docs


def test_limit_and_only_restrict_the_processing() -> None:
    drive, embedder, store = _setup()
    for i in range(4):
        drive.put(f"f{i}", f"Dossier/f{i}.md", f"Contenu {i}.")
    drive.put("x", "Autre/x.md", "Autre.")
    only = run_sync(drive, embedder, store, only="Autre/")
    assert only.indexed == 1 and set(store.docs) == {"x"}
    assert run_sync(drive, embedder, store, limit=2).indexed == 2
    assert run_sync(drive, embedder, store).indexed == 2  # le reste, à la passe suivante
