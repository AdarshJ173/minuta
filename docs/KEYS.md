# Keys & accounts

You bring all credentials. Nothing ships with the repo.

| Key | Where to get it | Used for | Required? |
|---|---|---|---|
| `DATABASE_URL` | Supabase → Connect → pooler (port 5432) | Postgres + pgvector | yes |
| `R2_*` | Cloudflare R2 → API tokens + private bucket | canonical JSON/Markdown | yes |
| `YOUTUBE_API_KEY` | Google Cloud Console → YouTube Data API v3 | discovery + metadata only | yes |
| `ADMIN_BOOTSTRAP_TOKEN` | you invent it (`openssl rand -hex 32`) | first admin login, then create scoped keys | yes |
| `APIFY_API_TOKEN` | console.apify.com → Settings → API & Integrations | transcript provider `apify` | pick ≥1 provider |
| `SUPADATA_API_KEY` | supadata.ai dashboard | transcript provider `supadata` | pick ≥1 provider |
| (none) | — | providers `ytdlp`, `yta` need no key | free but often blocked |

Set `TRANSCRIPT_PROVIDER_ORDER` to the providers you configured, e.g.
`apify,yta` or `supadata,yta`. First configured success wins.

## Scoped API keys (for agents)

Never hand out the bootstrap token. Create least-privilege keys:

```bash
curl -X POST "$PUBLIC_BASE_URL/admin/keys" \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
  -d '{"name":"agent-reader","scopes":["read","research"]}'
```

Store the returned `api_key` — it is shown once. Revoke with
`DELETE /admin/keys/{key_id}`.
