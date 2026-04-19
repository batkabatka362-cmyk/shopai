"""Semantic retrieval layer over MemoryIntelligence.

Stores per-memory embeddings in a sidecar SQLite table
(``memory_embeddings``) so the existing ``memories`` schema stays
untouched. Embedding happens lazily — the first ``index(mid, text)``
or ``index_pending()`` call is what triggers the Gemini API round
trip; retrieval queries use whatever has been indexed so far.

Public API:
    index(memory_id, text) → True on success
    index_pending(limit=20) → embed recent level>=1 memories (daemon hook)
    retrieve_similar(query, k=5, level_min=0) → [(memory_id, score, row)]
    stats() → {indexed, cache, dim}

Falls back to an empty result when the embedding client is unconfigured,
so the adapter layer's existing keyword/tag retrieval still works.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from . import embeddings as emb


logger = get_logger("memory.semantic_index")


_DB_PATH = Path("data/memory_intelligence.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id   INTEGER PRIMARY KEY,
    dim         INTEGER NOT NULL,
    embedding   TEXT NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_me_updated ON memory_embeddings(updated_at);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.executescript(_SCHEMA)
    return conn


def _text_for(row: dict[str, Any]) -> str:
    """Collapse a memory row into the text we'll embed. Title+tags+action
    is usually more signal-dense than the full content blob, which may
    be JSON with timestamps and ids.
    """
    cat = row.get("category", "")
    action = row.get("action", "")
    content = row.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            content = {}
    content_str = ""
    if isinstance(content, dict):
        parts = []
        for k in ("title", "strategy", "rule", "name", "description", "reason"):
            v = content.get(k)
            if v:
                parts.append(str(v))
        content_str = " ".join(parts)[:800]
    tags = row.get("tags", "")
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            tags = ", ".join(parsed) if isinstance(parsed, list) else tags
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("semantic_index tag parse failed: %s", exc)
    return f"category={cat} action={action} tags={tags} {content_str}".strip()


def index(memory_id: int, text: str) -> bool:
    """Embed *text* and store under *memory_id*. Overwrites any prior
    vector. Returns False when embedding is unconfigured / fails."""
    if memory_id <= 0 or not text:
        return False
    vec = emb.embed(text)
    if not vec:
        return False
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO memory_embeddings "
            "(memory_id, dim, embedding, updated_at) VALUES (?, ?, ?, ?)",
            (int(memory_id), len(vec), emb.encode_blob(vec), time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def index_pending(limit: int = 20, level_min: int = 1) -> dict[str, Any]:
    """Embed recent memories at level ≥ *level_min* that don't yet
    have an embedding. Caps at *limit* so we don't blow the API quota
    in a single cycle. Returns counts for the daemon phase."""
    if not emb.is_configured():
        return {"embedded": 0, "skipped": "embed_unconfigured"}

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.category, m.action, m.tags, m.content
              FROM memories m
              LEFT JOIN memory_embeddings e ON e.memory_id = m.id
             WHERE e.memory_id IS NULL
               AND m.level >= ?
               AND m.score >= 3.0
             ORDER BY m.last_used DESC, m.timestamp DESC
             LIMIT ?
            """,
            (int(level_min), int(max(1, limit))),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {"embedded": 0, "skipped": "nothing_pending"}

    embedded = 0
    for r in rows:
        row_dict = {
            "id": r[0], "category": r[1], "action": r[2],
            "tags": r[3], "content": r[4],
        }
        text = _text_for(row_dict)
        if not text:
            continue
        if index(row_dict["id"], text):
            embedded += 1
    return {"embedded": embedded, "candidates": len(rows)}


def retrieve_similar(
    query: str,
    k: int = 5,
    level_min: int = 0,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Return up to *k* memories whose embedding is closest to *query*.

    Each entry: ``{id, score, memory}`` where *memory* is the full
    memories-row dict. Empty list on any failure so callers can
    fall back to keyword retrieval.
    """
    if not query:
        return []
    qvec = emb.embed(query)
    if not qvec:
        return []

    conn = _conn()
    try:
        sql = (
            "SELECT e.memory_id, e.embedding, m.level, m.category, m.action, "
            "       m.content, m.tags, m.score, m.use_count, m.success_count "
            "  FROM memory_embeddings e "
            "  JOIN memories m ON m.id = e.memory_id "
            " WHERE m.level >= ?"
        )
        params: list[Any] = [int(level_min)]
        if category:
            sql += " AND m.category = ?"
            params.append(category)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        vec = emb.decode_blob(r[1])
        if not vec:
            continue
        sim = emb.cosine(qvec, vec)
        scored.append((sim, {
            "id": r[0],
            "level": r[2],
            "category": r[3],
            "action": r[4],
            "content": r[5],
            "tags": r[6],
            "score": r[7],
            "use_count": r[8],
            "success_count": r[9],
        }))
    scored.sort(key=lambda pair: -pair[0])
    return [{"id": m["id"], "score": round(s, 4), "memory": m}
            for s, m in scored[:k]]


def stats() -> dict[str, Any]:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), AVG(dim) FROM memory_embeddings")
        n, avg_dim = cur.fetchone() or (0, 0)
    finally:
        conn.close()
    return {
        "indexed": int(n or 0),
        "avg_dim": int(avg_dim or 0),
        "cache_size": emb.cache_size(),
        "configured": emb.is_configured(),
    }
