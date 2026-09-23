"""Synchronisation du Drive partagé vers la base de connaissances (Supabase).

Lancement : python -m app.kb.sync [--dry-run] [--limit N] [--only SOUS-CHAINE-DU-CHEMIN]

  --dry-run : lit, extrait et découpe les fichiers à traiter, sans calculer d'embeddings
              ni rien écrire en base (sert à valider l'extraction sur de vrais fichiers).
"""

import argparse
import hashlib
import logging
import sys
from dataclasses import asdict

from app.config import get_settings
from app.core.logging_config import configure_logging
from app.kb.chunk import chunk_text
from app.kb.drive import DriveClient
from app.kb.embed import Embedder, VertexEmbedder
from app.kb.extract import ExtractionError, extract_text, is_supported
from app.kb.store import KbStore, PostgresKbStore
from app.kb.types import DriveFile, IndexedDoc, SyncStats, parse_drive_time

logger = logging.getLogger(__name__)


def _decide(known: IndexedDoc | None, file: DriveFile) -> str:
    """'unchanged' | 'metadata' | 'process'"""
    if known is None or known.status == "error":
        return "process"
    if known.modified_time != parse_drive_time(file.modified_time):
        return "process"
    if known.name != file.name or known.folder_path != file.folder_path:
        return "metadata"
    return "unchanged"


def run_sync(
    drive,
    embedder: Embedder,
    store: KbStore,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    only: str | None = None,
) -> SyncStats:
    stats = SyncStats()
    files = drive.list_files()
    known = store.indexed()
    stats.seen = len(files)

    processed = 0
    for file in files:
        if only and only not in file.path:
            continue
        decision = _decide(known.get(file.id), file)
        if decision == "unchanged":
            stats.unchanged += 1
            continue
        if decision == "metadata":
            if not dry_run:
                store.touch_document(file)
            stats.touched += 1
            continue
        if limit is not None and processed >= limit:
            continue
        processed += 1

        if not is_supported(file.mime_type):
            if not dry_run:
                store.mark_document(file, "skipped", f"type non pris en charge : {file.mime_type}")
            stats.skipped += 1
            logger.info("kb_file_skipped", extra={"path": file.path, "reason": "type", "mime": file.mime_type})
            continue

        try:
            data, effective_mime = drive.fetch(file)
            text = extract_text(data, effective_mime)
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            previous = known.get(file.id)
            if previous and previous.status == "indexed" and previous.content_hash == content_hash:
                # Fichier retouché mais texte identique : inutile de recalculer les embeddings.
                if not dry_run:
                    store.touch_document(file)
                stats.touched += 1
                continue

            chunks = chunk_text(text)
            if dry_run:
                stats.indexed += 1
                stats.chunks_written += len(chunks)
                logger.info(
                    "kb_file_dry_run",
                    extra={"path": file.path, "mime": file.mime_type, "chars": len(text), "chunks": len(chunks)},
                )
                continue

            vectors = embedder.embed_documents([f"{file.path}\n\n{c.content}" for c in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
            store.save_document(file, content_hash, chunks, embedder.model)
            stats.indexed += 1
            stats.chunks_written += len(chunks)
            logger.info("kb_file_indexed", extra={"path": file.path, "chunks": len(chunks)})
        except ExtractionError as exc:
            if not dry_run:
                store.mark_document(file, "skipped", str(exc))
            stats.skipped += 1
            logger.info("kb_file_skipped", extra={"path": file.path, "reason": str(exc)})
        except Exception as exc:
            if not dry_run:
                store.mark_document(file, "error", f"{type(exc).__name__}: {exc}")
            stats.failed += 1
            logger.exception("kb_file_failed", extra={"path": file.path})

    # Fichiers disparus du Drive : on retire leurs morceaux de l'index.
    present = {f.id for f in files}
    gone = [file_id for file_id in known if file_id not in present]
    if gone and not files:
        # Liste vide alors que des documents sont indexés : bien plus probablement une perte d'accès
        # ou une erreur de l'API qu'un Drive réellement vidé. On ne détruit rien.
        logger.error("kb_delete_refused_empty_listing", extra={"indexed": len(known)})
    elif gone:
        if not dry_run:
            store.delete_documents(gone)
        stats.deleted = len(gone)
    return stats


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Synchronise le Drive partagé vers la base de connaissances.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="nombre max de fichiers à traiter")
    parser.add_argument("--only", default=None, help="ne traiter que les chemins contenant cette chaîne")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.kb_drive_id or not settings.kb_db_password:
        logger.error("kb_sync_not_configured", extra={"drive_id": bool(settings.kb_drive_id)})
        return 2

    store = PostgresKbStore(
        settings.kb_db_host, settings.kb_db_port, settings.kb_db_name, settings.kb_db_user, settings.kb_db_password
    )
    if not store.try_lock():
        logger.warning("kb_sync_already_running")
        store.close()
        return 0

    run_id: int | None = None
    try:
        if not args.dry_run:
            run_id = store.start_run()
        stats = run_sync(
            DriveClient(settings.kb_drive_id),
            VertexEmbedder(
                settings.kb_embedding_model, settings.kb_embedding_dim, settings.gcp_project, settings.gcp_region
            ),
            store,
            dry_run=args.dry_run,
            limit=args.limit,
            only=args.only,
        )
        if run_id is not None:
            store.finish_run(run_id, stats, "ok")
        logger.info("kb_sync_done", extra={**asdict(stats), "dry_run": args.dry_run})
        return 0
    except Exception as exc:
        logger.exception("kb_sync_failed")
        if run_id is not None:
            store.finish_run(run_id, SyncStats(), "error", f"{type(exc).__name__}: {exc}"[:500])
        return 1
    finally:
        store.unlock()
        store.close()


if __name__ == "__main__":
    sys.exit(main())
