"""API-key auth with scopes and a first-run bootstrap token."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from minuta.db import fetch_one, pool
from minuta.settings import get_settings

READ, RESEARCH, ADMIN = "read", "research", "admin"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_key(name: str, scopes: list[str]) -> dict:
    raw = f"vb_live_{secrets.token_urlsafe(24)}"
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into api_keys (name, key_hash, scopes) values (%s,%s,%s) returning id",
                (name, _hash(raw), scopes),
            )
            row = await cur.fetchone()
    return {"key_id": str(row["id"]), "api_key": raw, "scopes": scopes}


async def principal(token: str) -> dict | None:
    settings = get_settings()
    if settings.admin_bootstrap_token and hmac.compare_digest(token, settings.admin_bootstrap_token):
        return {"key_id": "bootstrap", "scopes": [ADMIN, READ, RESEARCH], "bootstrap": True}
    row = await fetch_one("select id, scopes from api_keys where key_hash=%s and revoked_at is null",
                          (_hash(token),))
    if not row:
        return None
    return {"key_id": str(row["id"]), "scopes": row["scopes"]}
