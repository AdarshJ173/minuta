"""YouTube Data API v3: channel resolution, uploads discovery, metadata.

The API key is used ONLY here, for official metadata and discovery.
It is never passed to caption extractors (it cannot authorize them).
"""

from __future__ import annotations

import re
from typing import Any

HANDLE_RE = re.compile(r"(?:youtube\.com/)?@([A-Za-z0-9._-]+)")
CHANNEL_RE = re.compile(r"(UC[A-Za-z0-9_-]{22})")
VIDEO_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")


class YouTubeQuotaExceeded(RuntimeError):
    pass


async def _get(client, path: str, params: dict, key: str) -> dict[str, Any]:
    from minuta.settings import get_settings

    resp = await client.get(
        f"https://www.googleapis.com/youtube/v3/{path}",
        params={**params, "key": get_settings().youtube_api_key},
    )
    if resp.status_code == 403 and "quota" in resp.text.lower():
        raise YouTubeQuotaExceeded(resp.text[:200])
    resp.raise_for_status()
    _ = key  # quota is tracked by the caller via response headers if needed
    return resp.json()


def parse_channel_input(raw: str) -> dict:
    raw = raw.strip()
    if m := CHANNEL_RE.search(raw):
        return {"kind": "channel_id", "value": m.group(1)}
    if m := HANDLE_RE.search(raw):
        return {"kind": "handle", "value": "@" + m.group(1)}
    if m := VIDEO_RE.search(raw):
        return {"kind": "video_id", "value": m.group(1)}
    return {"kind": "search", "value": raw}


async def resolve_channel(client, parsed: dict) -> dict[str, Any]:
    if parsed["kind"] == "channel_id":
        data = await _get(client, "channels", {"part": "id,snippet,contentDetails", "id": parsed["value"]}, "channels")
    elif parsed["kind"] == "handle":
        data = await _get(client, "channels", {"part": "id,snippet,contentDetails", "forHandle": parsed["value"]}, "channels")
    else:
        data = await _get(client, "search",
                          {"part": "snippet", "q": parsed["value"], "type": "channel", "maxResults": 1}, "search")
        if data.get("items"):
            cid = data["items"][0]["snippet"]["channelId"]
            return await resolve_channel(client, {"kind": "channel_id", "value": cid})
        raise ValueError(f"channel not found: {parsed['value']}")
    if not data.get("items"):
        raise ValueError(f"channel not found: {parsed['value']}")
    item = data["items"][0]
    return {
        "youtube_channel_id": item["id"],
        "title": item["snippet"]["title"],
        "description": item["snippet"].get("description", ""),
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
    }


async def list_uploads_page(client, playlist_id: str, cursor: str | None) -> dict:
    params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50}
    if cursor:
        params["pageToken"] = cursor
    data = await _get(client, "playlistItems", params, "playlistItems")
    return {
        "items": [
            {"youtube_video_id": it["contentDetails"]["videoId"], "title": it["snippet"]["title"]}
            for it in data.get("items", [])
            if it["contentDetails"].get("videoId")
        ],
        "next_page_token": data.get("nextPageToken"),
    }


async def get_videos(client, ids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(ids), 50):
        data = await _get(client, "videos",
                          {"part": "snippet,contentDetails,status", "id": ",".join(ids[i:i + 50])}, "videos")
        for it in data.get("items", []):
            sn = it["snippet"]
            out.append({
                "youtube_video_id": it["id"],
                "title": sn["title"],
                "description": sn.get("description", ""),
                "published_at": sn.get("publishedAt"),
                "channel_title": sn.get("channelTitle"),
                "privacy_status": it.get("status", {}).get("privacyStatus", "public"),
            })
    return out


async def captions(client, video_id: str) -> list[dict]:
    """Official caption-track listing (metadata only; download needs OAuth)."""
    data = await _get(client, "captions", {"part": "snippet", "videoId": video_id}, "captions")
    return [
        {"id": c["id"], "language": c["snippet"].get("language"),
         "track_kind": c["snippet"].get("trackKind"), "status": c["snippet"].get("status")}
        for c in data.get("items", [])
    ]
