"""Provider cooldowns (library_settings). Never retried automatically past expiry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from minuta.db import fetch_one


async def _get(key: str) -> dict | None:
    row = await fetch_one("select value from library_settings where key=%s", (key,))
    return (row or {}).get("value")


async def _set(key: str, value: dict) -> None:
    from minuta.db import pool

    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """insert into library_settings (key, value) values (%s, %s::jsonb)
                       on conflict (key) do update set value = excluded.value, updated_at = now()""",
                    (key, __import__("json").dumps(value)),
                )


async def get_cooldown(name: str = "transcript") -> datetime | None:
    value = await _get(f"provider_cooldown:{name}") or {}
    until = value.get("until")
    if not until:
        return None
    when = datetime.fromisoformat(until)
    return when if when > datetime.now(UTC) else None


async def set_cooldown(name: str, minutes: int, reason: str) -> datetime:
    until = datetime.now(UTC) + timedelta(minutes=minutes)
    await _set(f"provider_cooldown:{name}", {"until": until.isoformat(), "reason": reason})
    return until


async def clear_cooldown(name: str = "transcript") -> None:
    await _set(f"provider_cooldown:{name}", {"until": None, "reason": "cleared"})
