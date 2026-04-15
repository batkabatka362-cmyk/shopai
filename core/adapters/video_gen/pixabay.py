"""PixabayAdapter — Pixabay stock video search.

Pixabay (https://pixabay.com/api/docs/#api_videos) offers free
stock video (Pixabay license = public-domain-ish, credit not
required) under an API key. Complements Pexels with different
library coverage — when Pexels can't match the product niche,
Pixabay often does (and vice-versa).

Auth: API key passed as a query parameter (``key=<value>``),
NOT a header. Free tier: 100 req/min.
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import VideoGenBaseAdapter


class PixabayAdapter(VideoGenBaseAdapter):
    name = "pixabay"
    base_url = "https://pixabay.com/api/videos"
    config_alias = "pixabay"

    capabilities = {Capability.VIDEO_STOCK_SEARCH}

    # Lower priority than Pexels — smaller catalogue, less-rich
    # metadata. Still worth having for niche queries.
    priority = 75
    cost_per_call = 0.0

    kind = "stock"
    requires_key = True

    def _auth_headers(self) -> dict[str, str]:
        # Pixabay authenticates via query string, no header.
        return {
            "Accept": "application/json",
            "User-Agent": "ShopAI-VideoGen/1.0",
        }

    def _do_stock_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_stock_search(params)
        query = str(params["query"])
        limit = int(params.get("limit", 10))

        query_params: dict[str, Any] = {
            "key": self._api_key(),
            "q": query,
            # Pixabay's per_page minimum is 3; clamp to avoid 400s
            # when callers pass 1 or 2.
            "per_page": max(3, min(limit, 100)),
        }
        raw = self._http_request("GET", self.base_url, params=query_params)
        records = _extract_pixabay_clips(raw)
        return self._build_clips_response(
            capability, records, query=query, raw=raw,
        )


def _extract_pixabay_clips(raw: Any) -> list[dict[str, Any]]:
    """Map Pixabay ``hits`` → normalised clip records.

    Each hit has a ``videos`` dict keyed by quality label
    (``large``, ``medium``, ``small``, ``tiny``). We pick
    ``large`` when available, falling back through the tiers.
    """
    if not isinstance(raw, dict):
        return []
    hits = raw.get("hits")
    if not isinstance(hits, list):
        return []

    records: list[dict[str, Any]] = []
    for h in hits:
        if not isinstance(h, dict):
            continue
        videos = h.get("videos") or {}
        if not isinstance(videos, dict):
            videos = {}

        best = {}
        for tier in ("large", "medium", "small", "tiny"):
            candidate = videos.get(tier)
            if isinstance(candidate, dict) and candidate.get("url"):
                best = candidate
                break

        records.append({
            "clip_id":          str(h.get("id", "") or ""),
            "source":           "pixabay",
            "kind":             "stock",
            "status":           "ready",
            "video_url":        str(best.get("url", "") or ""),
            "thumbnail_url":    str(best.get("thumbnail", "") or ""),
            "duration_seconds": h.get("duration", 0),
            "width":            best.get("width", 0),
            "height":           best.get("height", 0),
            "format":           "mp4",
            "license":          "pixabay",
            "cost_usd":         0.0,
            "raw_url":          str(h.get("pageURL", "") or ""),
        })
    return records
