"""Stockage Supabase (schéma _jin_knowledge_base) via une connexion Postgres directe."""

import json
import logging
from typing import Protocol

from app.kb.types import Chunk, DriveFile, IndexedDoc, SyncStats, parse_drive_time

logger = logging.getLogger(__name__)

SCHEMA = "_jin_knowledge_base"
LOCK_KEY = 7401001  # verrou applicatif : un seul job de synchronisation à la fois


class KbStore(Protocol):
    def try_lock(self) -> bool: ...
    def unlock(self) -> None: ...
    def indexed(self) -> dict[str, IndexedDoc]: ...
    def save_document(self, file: DriveFile, content_hash: str, chunks: list[Chunk], model: str) -> None: ...
    def touch_document(self, file: DriveFile) -> None: ...
    def mark_document(self, file: DriveFile, status: str, error: str) -> None: ...
    def delete_documents(self, file_ids: list[str]) -> None: ...
    def start_run(self) -> int: ...
    def finish_run(self, run_id: int, stats: SyncStats, status: str, error: str | None = None) -> None: ...


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class PostgresKbStore:
    def __init__(self, host: str, port: int, dbname: str, user: str, password: str) -> None:
        import psycopg

        # Pooler Supabase (mode session) : pas de requêtes préparées côté client.
        self._conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=15,
        )

    def close(self) -> None:
        self._conn.close()

    def try_lock(self) -> bool:
        row = self._conn.execute("select pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()
        return bool(row and row[0])

    def unlock(self) -> None:
        self._conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))

    def indexed(self) -> dict[str, IndexedDoc]:
        rows = self._conn.execute(
            f"select file_id, name, coalesce(folder_path, ''), modified_time, content_hash, status from {SCHEMA}.documents"
        ).fetchall()
        return {r[0]: IndexedDoc(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows}

    def _upsert_document(
        self, file: DriveFile, status: str, error: str | None, chunk_count: int, content_hash: str | None
    ) -> None:
        self._conn.execute(
            f"""
            insert into {SCHEMA}.documents
              (file_id, name, mime_type, web_view_link, folder_path, modified_time, content_hash,
               status, error, chunk_count, indexed_at, updated_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    case when %s = 'indexed' then now() end, now())
            on conflict (file_id) do update set
              name = excluded.name, mime_type = excluded.mime_type, web_view_link = excluded.web_view_link,
              folder_path = excluded.folder_path, modified_time = excluded.modified_time,
              content_hash = excluded.content_hash, status = excluded.status, error = excluded.error,
              chunk_count = excluded.chunk_count,
              indexed_at = coalesce(excluded.indexed_at, {SCHEMA}.documents.indexed_at),
              updated_at = now()
            """,
            (
                file.id,
                file.name,
                file.mime_type,
                file.web_link,
                file.folder_path,
                parse_drive_time(file.modified_time),
                content_hash,
                status,
                error,
                chunk_count,
                status,
            ),
        )

    def save_document(self, file: DriveFile, content_hash: str, chunks: list[Chunk], model: str) -> None:
        """Réindexe un fichier : ses anciens morceaux sont remplacés, en une seule transaction."""
        with self._conn.transaction():
            self._upsert_document(file, "indexed", None, len(chunks), content_hash)
            self._conn.execute(f"delete from {SCHEMA}.chunks where file_id = %s", (file.id,))
            with self._conn.cursor() as cursor:
                cursor.executemany(
                    f"""
                    insert into {SCHEMA}.chunks
                      (file_id, chunk_index, content, token_count, metadata, embedding, embedding_model)
                    values (%s, %s, %s, %s, %s::jsonb, %s::public.vector, %s)
                    """,
                    [
                        (
                            file.id,
                            c.index,
                            c.content,
                            c.token_count,
                            json.dumps(c.metadata, ensure_ascii=False),
                            _vector_literal(c.embedding),
                            model,
                        )
                        for c in chunks
                    ],
                )

    def touch_document(self, file: DriveFile) -> None:
        """Le contenu n'a pas changé (fichier simplement touché, renommé ou déplacé) : métadonnées seules."""
        self._conn.execute(
            f"""
            update {SCHEMA}.documents
            set name = %s, folder_path = %s, web_view_link = %s, modified_time = %s, updated_at = now()
            where file_id = %s
            """,
            (file.name, file.folder_path, file.web_link, parse_drive_time(file.modified_time), file.id),
        )

    def mark_document(self, file: DriveFile, status: str, error: str) -> None:
        with self._conn.transaction():
            self._upsert_document(file, status, error[:500], 0, None)
            self._conn.execute(f"delete from {SCHEMA}.chunks where file_id = %s", (file.id,))

    def delete_documents(self, file_ids: list[str]) -> None:
        if file_ids:
            self._conn.execute(f"delete from {SCHEMA}.documents where file_id = any(%s)", (file_ids,))

    def start_run(self) -> int:
        row = self._conn.execute(f"insert into {SCHEMA}.sync_runs default values returning id").fetchone()
        assert row is not None
        return int(row[0])

    def finish_run(self, run_id: int, stats: SyncStats, status: str, error: str | None = None) -> None:
        self._conn.execute(
            f"""
            update {SCHEMA}.sync_runs
            set finished_at = now(), status = %s, files_seen = %s, files_indexed = %s,
                files_deleted = %s, files_failed = %s, error = %s
            where id = %s
            """,
            (status, stats.seen, stats.indexed, stats.deleted, stats.failed, error, run_id),
        )
