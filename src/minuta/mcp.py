"""Remote MCP server (Streamable HTTP): search + transcript tools, same auth."""

from __future__ import annotations

from fastmcp import FastMCP

from minuta import auth, search

mcp = FastMCP("minuta")


def _scopes(token: str) -> list[str]:
    import asyncio

    async def _lookup() -> list[str]:
        if (p := await auth.principal((token or "").removeprefix("Bearer ").strip())):
            return p["scopes"]
        return []

    return asyncio.run(_lookup())


@mcp.tool()
def search_transcripts(query: str, limit: int = 10, authorization: str = "") -> dict:
    """Hybrid search over indexed video transcripts. Returns timestamped passages."""
    import asyncio

    if auth.READ not in _scopes(authorization) and auth.ADMIN not in _scopes(authorization):
        return {"error": "unauthorized"}
    return asyncio.run(search.search_transcripts(query=query, limit=limit))


@mcp.tool()
def get_transcript(video_id: str, cursor: int | None = None,
                   page_size: int | None = None, authorization: str = "") -> dict:
    """Paged transcript retrieval with millisecond timestamps and ?t= links."""
    import asyncio

    if auth.READ not in _scopes(authorization) and auth.ADMIN not in _scopes(authorization):
        return {"error": "unauthorized"}
    try:
        return asyncio.run(search.get_transcript(video_id, mode="paged",
                                                 cursor=cursor, page_size=page_size))
    except ValueError as exc:
        return {"error": str(exc)}
