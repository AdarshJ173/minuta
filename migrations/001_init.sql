-- Minuta schema: channels, videos, transcript versions, chunks, jobs, keys.
-- Postgres + pgvector + pg_trgm. Supabase-compatible (Supavisor pooler OK).

create extension if not exists vector;
create extension if not exists pg_trgm;

create table if not exists channels (
  id uuid primary key default gen_random_uuid(),
  youtube_channel_id text unique not null,
  handle text not null default '',
  title text not null default '',
  description text not null default '',
  uploads_playlist_id text not null default '',
  discovery_cursor text,
  discovery_status text not null default 'pending',
  last_discovery_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists videos (
  id uuid primary key default gen_random_uuid(),
  channel_id uuid not null references channels(id) on delete cascade,
  youtube_video_id text unique not null,
  title text not null default '',
  description text not null default '',
  published_at timestamptz,
  duration_seconds integer,
  availability text not null default 'available',
  excluded boolean not null default false,
  transcript_status text not null default 'pending',
  transcript_attempts integer not null default 0,
  transcript_next_retry_at timestamptz,
  transcript_last_error text,
  indexing_status text not null default 'pending',
  last_processed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists videos_channel_idx on videos(channel_id);
create index if not exists videos_transcript_status_idx on videos(transcript_status);

create table if not exists transcript_versions (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references videos(id) on delete cascade,
  language text not null default 'en',
  source text not null default '',
  provider text not null default '',
  is_generated boolean,
  is_timed boolean not null default true,
  content_sha256 text not null default '',
  processing_version integer not null default 1,
  segment_count integer not null default 0,
  word_count integer not null default 0,
  duration_ms bigint,
  r2_json_key text not null default '',
  r2_markdown_key text not null default '',
  size_bytes integer not null default 0,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (video_id, language, content_sha256, processing_version)
);
create index if not exists tv_video_active_idx on transcript_versions(video_id, active);

create table if not exists chunks (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references videos(id) on delete cascade,
  transcript_version_id uuid not null references transcript_versions(id) on delete cascade,
  position integer not null default 0,
  text text not null default '',
  text_tsv tsvector generated always as (to_tsvector('english', text)) stored,
  embedding vector(384),
  start_ms bigint,
  end_ms bigint,
  embedding_model text not null default '',
  embedding_version text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists chunks_version_idx on chunks(transcript_version_id);
create index if not exists chunks_fts_idx on chunks using gin(text_tsv);
create index if not exists chunks_trgm_idx on chunks using gin(text gin_trgm_ops);
create index if not exists chunks_hnsw_idx on chunks using hnsw(embedding vector_cosine_ops);

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'queued'
    check (status in ('queued','running','succeeded','failed','canceled')),
  priority integer not null default 100,
  attempts integer not null default 0,
  max_attempts integer not null default 6,
  run_after timestamptz not null default now(),
  locked_at timestamptz,
  locked_by text,
  last_error text,
  result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists jobs_claim_idx on jobs(status, run_after, priority);

create table if not exists api_keys (
  id uuid primary key default gen_random_uuid(),
  name text not null default '',
  key_hash text unique not null,
  scopes text[] not null default '{read}',
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists library_settings (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
