#!/usr/bin/env bash
# First-run setup for humans AND coding agents. Safe to re-run.
# 1. copies .env.example -> .env (never overwrites)  2. venv + deps
# 3. prints the exact next steps. Secrets are never printed.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; echo "created .env — fill in the empty values (see docs/KEYS.md)"; }
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -q -r requirements.txt
echo "deps installed."
echo "next:"
echo "  1. fill .env (DATABASE_URL, R2_*, YOUTUBE_API_KEY, ADMIN_BOOTSTRAP_TOKEN, + one transcript provider)"
echo "  2. PYTHONPATH=src .venv/bin/python -m minuta.migrate"
echo "  3. PYTHONPATH=src .venv/bin/python scripts/backfill.py --help"
echo "  4. PYTHONPATH=src .venv/bin/pytest -q"
