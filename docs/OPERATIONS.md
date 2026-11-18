# Operations

## Deploy (Modal)

```bash
modal token new                       # once per machine
bash scripts/make_secret.sh           # builds secret `minuta` from .env
modal run modal_app.py --action migrate
modal deploy modal_app.py
modal run modal_app.py --action backfill --minutes 45
```

The `worker_tick` function runs every 5 minutes on Modal's scheduler and
drains the queue continuously. Use `backfill` for bulk runs.

## Deploy (Docker / anywhere)

```bash
docker build -t minuta .
docker run -p 8080:8080 --env-file .env minuta
python scripts/backfill.py --max 200 --sleep 15   # separate process/machine
```

## Cooldowns

Rate limits set `provider_cooldown:transcript` in `library_settings`.
Inspect: `select value from library_settings where key like 'provider_cooldown%'`.
Clear (only when the blocking cause is gone):
`PYTHONPATH=src python -c "import asyncio; from minuta.provider_state import clear_cooldown; asyncio.run(clear_cooldown())"`.

## Turbo (paid speed)

See [TURBO.md](TURBO.md): `TRANSCRIPT_PROVIDER_ORDER=transcriptapi,supadata,apify`,
`EMBEDDING_PROVIDER=openai`, `WORKER_CONCURRENCY=16`,
`python scripts/backfill.py --max 500 --concurrency 12 --sleep 0`.
Comma-separated `YOUTUBE_API_KEY` values rotate quota automatically.

## Costs (2026 prices)

- Apify free plan: $5/mo usage, no card; actor ≈ $0.70/1k transcripts.
  ~150 videos ≈ $0.11. Free-plan overage blocks instead of charging.
- Supadata free tier: 100 credits/month (1 credit ≈ 1 transcript).
- Modal: scale-to-zero; a full backfill stays in low single-digit dollars.
