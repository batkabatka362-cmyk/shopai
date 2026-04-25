"""Pexels photo search — simple HTTP client.

Not routed through the adapter framework because the launch pipeline
just needs a keyword → photo URL lookup. If the key is unset the
``search`` function returns an empty list so callers can fall back to
supplier-provided gallery images.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from utils.logger import get_logger


logger = get_logger("adapters.image.pexels")

_PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def is_configured() -> bool:
    return bool(os.environ.get("PEXELS_API_KEY"))


def search(query: str, per_page: int = 5, orientation: str = "landscape") -> list[dict]:
    """Return a list of ``{url, photographer, width, height, alt}`` dicts.

    Silently returns ``[]`` on network errors, unconfigured key, or
    empty result — callers should treat this as an optional enhancer.
    """
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key or not query:
        return []

    params = urllib.parse.urlencode({
        "query": query,
        "per_page": max(1, min(int(per_page), 15)),
        "orientation": orientation,
    })
    url = f"{_PEXELS_SEARCH_URL}?{params}"
    # Cloudflare in front of api.pexels.com returns 403 for the default
    # ``Python-urllib/...`` user agent. Use a normal UA string.
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": api_key,
            "User-Agent": "ShopAI/1.0 (+https://github.com/batkabatka362-cmyk/shopai)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Pexels search failed for %r: %s", query, exc)
        return []

    photos = []
    for p in data.get("photos", []):
        src = p.get("src", {}) or {}
        url_large = src.get("large2x") or src.get("large") or src.get("original")
        if not url_large:
            continue
        photos.append({
            "url": url_large,
            "photographer": p.get("photographer", ""),
            "width": p.get("width", 0),
            "height": p.get("height", 0),
            "alt": p.get("alt", ""),
            "pexels_id": p.get("id"),
        })
    return photos
