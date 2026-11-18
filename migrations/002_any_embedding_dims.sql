-- 002: allow any embedding dimension (turbo/API embedding models).
-- Local BGE-small uses 384 dims; paid API models use 768-3072. An
-- unconstrained `vector` column accepts both; HNSW is rebuilt once.
-- Search filters by embedding_model + embedding_version, so mixed rows
-- from a mid-migration table cannot break queries.
-- Run `python -m minuta.migrate` after pulling. Autocommit is on, so
-- CONCURRENTLY does not block writes.

drop index if exists chunks_hnsw_idx;
alter table chunks alter column embedding type vector;
create index concurrently if not exists chunks_hnsw_idx
  on chunks using hnsw (embedding vector_cosine_ops);
