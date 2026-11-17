# AGENTS.md — instructions for coding agents working in this repo

Read this before changing anything. The user-facing setup contract is
`README.md` (quickstart) + `llms.txt` (API surface). Keep both accurate.

## Non-negotiables

1. **Never invent timestamps.** Untimed sources stay untimed (`NULL`).
   `text.py::build_document` enforces this; don't bypass it.
2. **Error taxonomy is load-bearing.** `unavailable` = definitive (record it),
   `temporary` = backoff + global cooldown, `disabled` = misconfigured,
   `auth-required` = stop and ask the human. A blocked fallback must never
   trigger a global cooldown when the primary already answered
   (see `pipeline.py` + `test_chain.py`).
3. **One provider at a time per video.** Never run competing transcript
   providers simultaneously against the same video.
4. **No secrets in code, logs, tests, or fixtures.** Tests use
   `httpx.MockTransport`. `.env` is gitignored; `.env.example` has placeholders only.
5. **Verify with execution.** `ruff check` + `pytest -q` before every commit.
   One targeted live check beats ten mocked ones, but never hammer
   rate-limited endpoints: single attempts, backoff, stop on blocks.
6. **Commit shape.** Small coherent commits; no drive-by refactors.

## Layout

- `src/minuta/` — all code (`transcripts/` = providers + `pipeline.py` chain)
- `migrations/` — SQL, applied in filename order by `minuta.migrate`
- `scripts/` — `setup.sh`, `backfill.py`, `make_secret.sh`
- `tests/` — offline only (no network, no credentials)
- `docs/` — ARCHITECTURE, KEYS, OPERATIONS

## Common tasks

- Add a provider: implement `base.TranscriptProvider` in
  `transcripts/<name>.py`, register in `pipeline.providers()`, document in
  `.env.example` + `docs/KEYS.md`, add offline tests with `MockTransport`.
- Change error semantics: update `tests/test_chain.py` FIRST, then code.
