# Contributing

Minuta stays small on purpose. The fastest way to help: fix a real failure
you hit, with a test that would have caught it.

## Ground rules

1. Small, coherent commits. No drive-by refactors.
2. `ruff check src tests` and `PYTHONPATH=src pytest -q` green before every push.
3. Tests are offline only: `httpx.MockTransport`, fixtures in-code.
   No network, no credentials, no VCR cassettes with real tokens.
4. Never invent timestamps. Untimed sources stay untimed.
5. Never commit secrets: `.env`, tokens, keys, channel IDs of private
   libraries, dataset contents. `.env.example` keeps placeholders only.
6. Error taxonomy is load-bearing (`unavailable` / `temporary` / `disabled` /
   `auth-required`). Changing it requires updating `tests/test_chain.py` first.

## Adding a transcript provider

1. Implement `base.TranscriptProvider` in `src/minuta/transcripts/<name>.py`.
2. Register it in `transcripts/pipeline.py::providers()`.
3. Document its key in `.env.example` + `docs/KEYS.md`.
4. Add offline tests with `MockTransport` (success + definitive + transient).
