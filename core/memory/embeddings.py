"""Semantic embeddings for MemoryIntelligence.

Converts memory content into dense vectors (Gemini embedding-001,
3072 dims) so retrieval can use cosine similarity instead of the
existing Jaccard/keyword match. Enables:

    similar("wireless earbuds") →
        top-K memories whose content is conceptually close,
        not just textually overlapping

Design:
  • Fast in-process cache (dict) to avoid re-embedding identical text
  • Lazy — embed only when called, not on every memory.create()
  • Cosine in pure Python (numpy optional; we already ship numpy)
  • Failure isolation — a dead API key just returns [] (retriever
    falls back to the keyword path)
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from utils.logger import get_logger


logger = get_logger("memory.embeddings")


_GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-001:embedContent"
)
_DIM = 3072
_MAX_CHARS = 8_000  # defensive — API limit is higher but we don't need more
_CACHE: dict[str, list[float]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 2_048


def is_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def embed(text: str) -> list[float]:
    """Return a 3072-dim embedding for *text*. Empty list on failure.

    Results are cached by text content (first ``_MAX_CHARS`` chars)
    so repeat queries in the same process are free."""
    if not text or not isinstance(text, str):
        return []
    key = text[:_MAX_CHARS]
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return []

    body = json.dumps({
        "content": {"parts": [{"text": key}]},
    }).encode("utf-8")
    req = urllib.request.Request(
        _GEMINI_EMBED_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("embed failed: %s", exc)
        return []

    vec = data.get("embedding", {}).get("values") or []
    if not vec or len(vec) != _DIM:
        return []
    vec = [float(v) for v in vec]
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            # Evict oldest — simple strategy
            _CACHE.pop(next(iter(_CACHE)), None)
        _CACHE[key] = vec
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0 for any degenerate
    input (empty vector, zero norm). Pure Python — no numpy import
    in the hot path."""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        num += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return num / (math.sqrt(na) * math.sqrt(nb))


def encode_blob(vec: list[float]) -> str:
    """Serialise an embedding to a compact JSON string for sqlite
    storage. Round to 6 decimals — overkill for cosine precision
    but keeps the stored string under 70 kB per vector."""
    return json.dumps([round(float(v), 6) for v in vec])


def decode_blob(blob: str) -> list[float]:
    if not blob:
        return []
    try:
        return [float(v) for v in json.loads(blob)]
    except (json.JSONDecodeError, ValueError):
        return []


def cache_size() -> int:
    with _CACHE_LOCK:
        return len(_CACHE)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


# ── Diagnostics ─────────────────────────────────────────────

def self_test() -> dict[str, Any]:
    """Small smoke test — useful when wiring the adapter. Emits a
    dict you can log or serve over /api/status."""
    start = time.monotonic()
    configured = is_configured()
    vec = embed("A sample product description for testing embedding quality")
    elapsed = time.monotonic() - start
    return {
        "configured": configured,
        "dim": len(vec),
        "latency_s": round(elapsed, 2),
        "cache_size": cache_size(),
    }
