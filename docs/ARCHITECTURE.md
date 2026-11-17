# Architecture

```
YouTube ──Data API──▶ discovery (channels, uploads, metadata)
   │                     (API key = metadata only; never unlocks captions)
   │
   ├── transcript providers (first configured success wins)
   │     apify ──▶ Store actor, timestamped JSON, ~$0.70/1k
   │     ytdlp ──▶ subtitle-only VTT, manual-first, rolling-dedupe
   │     yta   ──▶ youtube-transcript-api (often IP-blocked)
   │     supadata ─▶ paid API, 100 free credits/mo
   │
   ▼
canonical doc (JSON + Markdown, content-hashed, idempotent)
   ├──▶ R2 private bucket (content-addressed keys)
   └──▶ Postgres version row ──▶ chunker ──▶ ONNX embeddings ──▶ chunks
         (pgvector HNSW + FTS + trigram)
   │
   ├──▶ REST  (/v1/search, /v1/videos/:id/transcript)
   └──▶ MCP   (Streamable HTTP, same Bearer auth)
```

## Key decisions

1. **Content hash = identity.** Re-imports and re-fetches of identical text
   resolve to one version and one chunk set. Indexing is idempotent.
2. **Timestamps are never invented.** Untimed sources stay untimed (`NULL`),
   clearly labeled in the Markdown export.
3. **Error taxonomy, not booleans.** `unavailable` (definitive) vs
   `temporary` (backoff + global cooldown) vs `disabled` (misconfigured) vs
   `auth-required` (human approval, never auto-retried). A blocked *fallback*
   never overrides the primary provider's definitive answer and never sets a
   global cooldown on its behalf.
4. **No competing providers.** One Actor/subprocess at a time per worker;
   concurrency caps keep cloud IP usage under free-tier rate limits.
5. **Local embeddings.** BGE-small via fastembed/ONNX: no key, no network,
   no training. Vectors are computed and indexed, never learned from.
6. **Transcript text is untrusted data.** It is quoted and cited, never
   executed; logs redact secrets (see `settings.redaction_values`).
