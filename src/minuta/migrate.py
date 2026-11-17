"""Single-file migration runner. Applies migrations/*.sql in order."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg


def _database_url() -> str:
    for line in Path(".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    sys.exit("DATABASE_URL missing from .env")


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "migrations"
    files = sorted(root.glob("*.sql"), key=lambda p: p.name)
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """create table if not exists schema_migrations
                   (name text primary key, applied_at timestamptz default now())"""
            )
            applied = {r[0] for r in cur.execute("select name from schema_migrations").fetchall()}
            for path in files:
                if path.name in applied:
                    print(f"skip {path.name}")
                    continue
                statements = [s for s in re.split(r";\s*\n", path.read_text()) if s.strip()]
                for statement in statements:
                    cur.execute(statement)
                cur.execute("insert into schema_migrations (name) values (%s)", (path.name,))
                print(f"applied {path.name}")


if __name__ == "__main__":
    main()
