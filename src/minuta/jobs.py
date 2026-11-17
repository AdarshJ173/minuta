"""Durable job queue over Postgres."""

from __future__ import annotations

import json
from typing import Any

from minuta.db import pool


async def enqueue(kind: str, payload: dict[str, Any], *, priority: int = 100,
                 max_attempts: int = 6) -> str | None:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """insert into jobs (kind, payload, priority, max_attempts)
                   values (%s, %s::jsonb, %s, %s)
                   on conflict do nothing returning id""",
                (kind, json.dumps(payload), priority, max_attempts),
            )
            row = await cur.fetchone()
            return str(row["id"]) if row else None


async def claim(worker_id: str, limit: int = 4) -> list[dict]:
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """with candidate as (
                         select id from jobs
                         where status = 'queued' and run_after <= now()
                         order by priority asc, run_after asc limit %(limit)s
                         for update skip locked
                       )
                       update jobs j set status='running', locked_by=%(worker)s,
                         attempts = j.attempts + 1
                       from candidate c where j.id = c.id returning j.*""",
                    {"limit": limit, "worker": worker_id},
                )
                return await cur.fetchall()


async def complete(job_id: str, result: dict | None = None) -> None:
    from minuta.db import execute

    await execute("update jobs set status='succeeded', result=%s::jsonb where id=%s",
                  (json.dumps(result or {}), job_id))


async def fail(job_id: str, error: str, *, retryable: bool, delay_seconds: int = 300) -> None:
    from minuta.db import execute

    if retryable:
        await execute(
            """update jobs set status='queued', last_error=%s,
               run_after = now() + (%s || ' seconds')::interval where id=%s""",
            (error[:1500], str(delay_seconds), job_id),
        )
    else:
        await execute("update jobs set status='failed', last_error=%s where id=%s",
                      (error[:1500], job_id))
