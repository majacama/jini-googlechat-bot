-- Base de connaissances du bot Google Chat (RAG sur un Drive partagé).
-- Projet Supabase : JIN APPS. Schéma dédié, isolé de _ask_jin_fr, _engage_jin_fr, etc.
--
-- Rejouable (IF NOT EXISTS / CREATE OR REPLACE). Appliquer avec :
--   supabase db query --linked --workdir <dossier lié à JIN APPS> -f db/migrations/001_jin_knowledge_base.sql
--
-- Le mot de passe du rôle jin_kb_bot n'est volontairement PAS ici : il est posé à part
-- (ALTER ROLE ... PASSWORD) et stocké dans Secret Manager (secret jin-kb-db-password).
--
-- pgvector est déjà installé dans le schéma public (0.8.0) : les types et opérateurs
-- sont donc qualifiés par public.

create schema if not exists _jin_knowledge_base;
comment on schema _jin_knowledge_base is
  'Base de connaissances du bot Google Chat : morceaux de documents d''un Drive partagé, vectorisés.';

-- Un enregistrement par fichier Drive indexé.
create table if not exists _jin_knowledge_base.documents (
  file_id        text primary key,                 -- identifiant Drive du fichier
  name           text not null,
  mime_type      text,
  web_view_link  text,                             -- lien « Ouvrir dans Drive »
  folder_path    text,
  modified_time  timestamptz,                      -- modifiedTime Drive, sert à détecter un changement
  content_hash   text,                             -- empreinte du contenu (md5 Drive ou du texte extrait)
  status         text not null default 'indexed'
                 check (status in ('indexed', 'skipped', 'error')),
  error          text,
  chunk_count    integer not null default 0,
  indexed_at     timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- Morceaux de texte vectorisés. Réindexer un fichier = supprimer ses morceaux puis réinsérer.
create table if not exists _jin_knowledge_base.chunks (
  id               bigint generated always as identity primary key,
  file_id          text not null references _jin_knowledge_base.documents (file_id) on delete cascade,
  chunk_index      integer not null,
  content          text not null,
  token_count      integer,
  metadata         jsonb not null default '{}'::jsonb,   -- section, page, etc.
  embedding        public.vector(1536) not null,         -- vecteurs normalisés : distance cosinus
  embedding_model  text not null,                        -- modèle utilisé, pour pouvoir migrer proprement
  fts              tsvector generated always as (to_tsvector('french', content)) stored,
  created_at       timestamptz not null default now(),
  unique (file_id, chunk_index)
);

create index if not exists chunks_embedding_hnsw
  on _jin_knowledge_base.chunks using hnsw (embedding public.vector_cosine_ops);
create index if not exists chunks_fts_gin
  on _jin_knowledge_base.chunks using gin (fts);

-- Journal des passages du job de synchronisation.
create table if not exists _jin_knowledge_base.sync_runs (
  id             bigint generated always as identity primary key,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  status         text not null default 'running' check (status in ('running', 'ok', 'error')),
  files_seen     integer not null default 0,
  files_indexed  integer not null default 0,
  files_deleted  integer not null default 0,
  files_failed   integer not null default 0,
  error          text
);

-- Recherche par similarité (cosinus). similarity = 1 - distance.
create or replace function _jin_knowledge_base.match_chunks(
  query_embedding  public.vector(1536),
  match_count      integer default 8,
  min_similarity   double precision default 0.0
)
returns table (
  file_id        text,
  name           text,
  web_view_link  text,
  chunk_index    integer,
  content        text,
  similarity     double precision
)
language sql
stable
set search_path = public
as $$
  select c.file_id, d.name, d.web_view_link, c.chunk_index, c.content,
         1 - (c.embedding <=> query_embedding) as similarity
  from _jin_knowledge_base.chunks c
  join _jin_knowledge_base.documents d on d.file_id = c.file_id
  where d.status = 'indexed'
    and 1 - (c.embedding <=> query_embedding) >= min_similarity
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

-- Sécurité : RLS activée partout (refus par défaut), un seul rôle applicatif autorisé.
alter table _jin_knowledge_base.documents enable row level security;
alter table _jin_knowledge_base.chunks    enable row level security;
alter table _jin_knowledge_base.sync_runs enable row level security;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'jin_kb_bot') then
    create role jin_kb_bot login noinherit nosuperuser nocreatedb nocreaterole nobypassrls;
  end if;
end
$$;

-- Aucun accès via l'API publique de Supabase (anon / authenticated).
revoke all on schema _jin_knowledge_base from anon, authenticated;
revoke all on all tables in schema _jin_knowledge_base from anon, authenticated;
revoke all on all functions in schema _jin_knowledge_base from anon, authenticated;

grant usage on schema _jin_knowledge_base to jin_kb_bot;
grant select, insert, update, delete on all tables in schema _jin_knowledge_base to jin_kb_bot;
grant usage, select on all sequences in schema _jin_knowledge_base to jin_kb_bot;
grant execute on all functions in schema _jin_knowledge_base to jin_kb_bot;

drop policy if exists bot_all_documents on _jin_knowledge_base.documents;
create policy bot_all_documents on _jin_knowledge_base.documents
  for all to jin_kb_bot using (true) with check (true);

drop policy if exists bot_all_chunks on _jin_knowledge_base.chunks;
create policy bot_all_chunks on _jin_knowledge_base.chunks
  for all to jin_kb_bot using (true) with check (true);

drop policy if exists bot_all_sync_runs on _jin_knowledge_base.sync_runs;
create policy bot_all_sync_runs on _jin_knowledge_base.sync_runs
  for all to jin_kb_bot using (true) with check (true);
