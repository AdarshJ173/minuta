"""Async Postgres pool (Supavisor-compatible) plus tiny query helpers."""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from minuta.settings import get_settings

_pool: AsyncConnectionPool | None = None


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        pool = AsyncConnectionPool(
            conninfo=get_settings().database_url,
            min_size=1,
            max_size=8,
            timeout=15,
            kwargs={"row_factory": dict_row, "application_name": "minuta"},
            open=False,
        )
        await pool.open(wait=True, timeout=30)
        _pool = pool
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("database pool is not open")
    return _pool


async def fetch_all(query: str, params: dict | tuple | None = None) -> list[dict]:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def fetch_one(query: str, params: dict | tuple | None = None) -> dict | None:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()


async def execute(query: str, params: dict | tuple | None = None) -> int:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return cur.rowcount
