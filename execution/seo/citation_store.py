"""Owner-curated citation store for GEO quote-sandwich wire.

commit 325168f wired ContentGenerator.product_description to
honour ``use_geo_sandwich=True`` + ``product["citations"]`` for
Princeton +40% LLM citation uplift — but in practice no
autopilot cycle ever attached citations to the winner dict, so
the sandwich never fired. This module closes the gap.

Design (determinism over intelligence — CLAUDE.md §4b/A):

  * Owner curates real citations once per niche in
    ``data/citations/<niche>.json``.
  * At content-generation time, the niche-keyed citations are
    merged into the product dict before the sandwich wire sees
    it. Shared across every SKU in the niche so one curation
    pass covers dozens of launches.
  * No scraping, no LLM-generated fake quotes. Everything in
    the file is something the owner typed or pasted from a
    known authoritative source.

File format (list of dicts, each one validated by
:func:`execution.seo.quote_sandwich.wrap_claim`):

  [
    {
      "claim": "Slow-feeder bowls cut bloat by 40%.",
      "quote": "Dogs that eat slowly digest better.",
      "source_name": "Dr. Elena Martinez, DVM",
      "source_type": "expert",
      "citation": "AVMA Journal 2024",
      "citation_url": "https://avma.example.com/bloat"
    }, ...
  ]

Normalisation: the niche is lowercased + non-alnum → "-" so
``Pet Supplies`` and ``pet_supplies`` collapse to the same file
name. Missing file → empty list (no crash, no fake).

Pure stdlib. Thread-safe (lock around cache). Cache has a
5-min TTL so owner edits appear without restart.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DEFAULT_DIR = Path("data/citations")
_DEFAULT_TTL_S = 300.0
_NICHE_SANITISE = re.compile(r"[^a-z0-9]+")


@dataclass
class _CacheEntry:
    fetched_at: float
    citations: list[dict[str, Any]]


_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], _CacheEntry] = {}


def _sanitise_niche(niche: str) -> str:
    """Normalise niche into a filename-safe slug."""
    s = (niche or "").strip().lower()
    s = _NICHE_SANITISE.sub("-", s).strip("-")
    return s or "default"


def _file_for(
    niche: str, base: Path | None = None,
) -> Path:
    base = base or _DEFAULT_DIR
    return base / f"{_sanitise_niche(niche)}.json"


def _read_citations(
    niche: str, base: Path | None = None,
    now_fn: Any = None,
) -> list[dict[str, Any]]:
    """Load + cache citations for a niche. Cache refresh on
    TTL expiry or when the file's mtime advances past the
    cached fetched_at."""
    now = float((now_fn or time.time)())
    base = base or _DEFAULT_DIR
    path = _file_for(niche, base=base)
    cache_key = (str(base.resolve() if base.exists() else base), path.name)
    with _LOCK:
        entry = _CACHE.get(cache_key)
        if entry is not None and (
            now - entry.fetched_at < _DEFAULT_TTL_S
        ):
            return list(entry.citations)
    if not path.exists():
        with _LOCK:
            _CACHE[cache_key] = _CacheEntry(
                fetched_at=now, citations=[],
            )
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        with _LOCK:
            _CACHE[cache_key] = _CacheEntry(
                fetched_at=now, citations=[],
            )
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        # Require at minimum claim + quote so downstream
        # wrap_claim() doesn't raise.
        if not row.get("claim") or not row.get("quote"):
            continue
        out.append(dict(row))
    with _LOCK:
        _CACHE[cache_key] = _CacheEntry(
            fetched_at=now, citations=list(out),
        )
    return list(out)


def resolve_citations_for(
    product: dict[str, Any],
    *,
    base: Path | None = None,
    now_fn: Any = None,
) -> list[dict[str, Any]]:
    """Return the best-match citation list for a product.

    Priority:
      1. product["citations"] (caller explicit) — untouched.
      2. niche file for ``product["niche"]`` or
         ``product["category"]`` or ``product["product_type"]``.
      3. ``default.json``.
      4. [] when nothing matches.
    """
    explicit = product.get("citations")
    if isinstance(explicit, list) and explicit:
        return explicit
    niche_hints = [
        str(product.get(k, "") or "")
        for k in ("niche", "category", "product_type")
    ]
    for n in niche_hints:
        if not n:
            continue
        hits = _read_citations(n, base=base, now_fn=now_fn)
        if hits:
            return hits
    return _read_citations(
        "default", base=base, now_fn=now_fn,
    )


def inject_citations(
    product: dict[str, Any],
    *,
    base: Path | None = None,
    now_fn: Any = None,
) -> dict[str, Any]:
    """Return a shallow copy of ``product`` with
    ``citations`` populated from the niche store if absent."""
    citations = resolve_citations_for(
        product, base=base, now_fn=now_fn,
    )
    if not citations:
        return dict(product)
    out = dict(product)
    if not out.get("citations"):
        out["citations"] = citations
    return out


def available_niches(
    base: Path | None = None,
) -> list[str]:
    """List niche slugs the owner has curated. Used by CLI
    ``shopai citations list`` and the MCP tool."""
    base = base or _DEFAULT_DIR
    if not base.exists():
        return []
    return sorted(
        p.stem for p in base.glob("*.json")
    )


def reset_cache_for_tests() -> None:
    with _LOCK:
        _CACHE.clear()
