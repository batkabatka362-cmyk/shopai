"""PexelsAdapter — free stock video search.

Pexels (https://pexels.com/api/) offers a free, keyed API
returning royalty-free stock video clips. It's the primary
cheap source for the "stock + voiceover" creative path —
combine a Pexels clip with an ElevenLabs voiceover and the
total creative cost is ~$0.20-0.50 per video (just the TTS).

Authentication: the API key is sent in the ``Authorization``
header (no ``Bearer`` prefix) — Pexels accepts the key value
directly. Free tier: 200 requests/hour, 20000/month.

Endpoints:

  * ``GET /videos/search`` — keyword search
  * ``GET /videos/popular`` — trending (used as trending query
    when no explicit query is given, but we require an explicit
    query to match the adapter contract)

Reference: https://www.pexels.com/api/documentation/#videos
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import VideoGenBaseAdapter


class PexelsAdapter(VideoGenBaseAdapter):
    name = "pexels"
    base_url = "https://api.pexels.com/videos"
    config_alias = "pexels"

    # Stock-search-only adapter. VIDEO_GENERATE / VIDEO_GET_STATUS
    # are not supported — calling them raises AdapterValidationError
    # via the base's _execute guard.
    capabilities = {Capability.VIDEO_STOCK_SEARCH}

    # Highest priority among stock sources: largest library,
    # best matching relevance, free tier is generous.
    priority = 90
    # Free tier → effectively $0. We leave a tiny non-zero value
    # so the router weighs paid calls slightly less (quota is
    # finite — 20k/month).
    cost_per_call = 0.0

    kind = "stock"
    requires_key = True

    def _auth_headers(self) -> dict[str, str]:
        # Pexels uses the raw key (no "Bearer" prefix).
        return {
            "Authorization": self._api_key(),
            "Accept": "application/json",
            "User-Agent": "ShopAI-VideoGen/1.0",
        }

    def _do_stock_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_stock_search(params)
        query = str(params["query"])
        limit = int(params.get("limit", 10))
        # Orientation & size pass-through: let the engine ask for
        # portrait (TikTok/Reels) or landscape (YouTube) clips.
        orientation = str(params.get("orientation", "") or "")
        size = str(params.get("size", "") or "")

        url = f"{self.base_url}/search"
        query_params: dict[str, Any] = {
            "query": query,
            "per_page": limit,
        }
        if orientation in ("portrait", "landscape", "square"):
            query_params["orientation"] = orientation
        if size in ("small", "medium", "large"):
            query_params["size"] = size

        raw = self._http_request("GET", url, params=query_params)
        records = _extract_pexels_clips(raw)
        return self._build_clips_response(
            capability, records, query=query, raw=raw,
        )


def _extract_pexels_clips(raw: Any) -> list[dict[str, Any]]:
    """Map Pexels response shape → normalised clip records.

    Pexels returns video files in a nested ``video_files`` list,
    each with a ``link``, ``width``, ``height``, ``quality``, and
    ``file_type``. We pick the largest MP4 per video as the
    canonical ``video_url`` so downstream compositing gets
    highest quality, and keep the original vendor id + page
    URL for traceability.
    """
    if not isinstance(raw, dict):
        return []
    videos = raw.get("videos")
    if not isinstance(videos, list):
        return []

    records: list[dict[str, Any]] = []
    for v in videos:
        if not isinstance(v, dict):
            continue
        # Find the best MP4 file — prefer the highest resolution.
        best_url = ""
        best_width = 0
        best_height = 0
        best_format = ""
        files = v.get("video_files") or []
        if isinstance(files, list):
            for f in files:
                if not isinstance(f, dict):
                    continue
                file_type = str(f.get("file_type", "") or "")
                # Prefer MP4 (video/mp4). Skip HLS/other containers.
                if "mp4" not in file_type.lower():
                    continue
                try:
                    w = int(f.get("width", 0) or 0)
                    h = int(f.get("height", 0) or 0)
                except (TypeError, ValueError):
                    w, h = 0, 0
                if w * h > best_width * best_height:
                    best_url = str(f.get("link", "") or "")
                    best_width = w
                    best_height = h
                    best_format = "mp4"

        # Thumbnail lives in ``video_pictures[0].picture`` or the
        # top-level ``image`` field (older responses).
        thumb = ""
        pictures = v.get("video_pictures") or []
        if isinstance(pictures, list) and pictures:
            first = pictures[0]
            if isinstance(first, dict):
                thumb = str(first.get("picture", "") or "")
        if not thumb:
            thumb = str(v.get("image", "") or "")

        records.append({
            "clip_id":          str(v.get("id", "") or ""),
            "source":           "pexels",
            "kind":             "stock",
            "status":           "ready",
            "video_url":        best_url,
            "thumbnail_url":    thumb,
            "duration_seconds": v.get("duration", 0),
            "width":            best_width or v.get("width", 0),
            "height":           best_height or v.get("height", 0),
            "format":           best_format or "mp4",
            "license":          "pexels",
            "cost_usd":         0.0,
            "raw_url":          str(v.get("url", "") or ""),
        })
    return records
