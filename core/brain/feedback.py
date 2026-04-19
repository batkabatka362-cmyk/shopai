"""Human feedback — RLHF-lite.

The brain's memory score (1-5) previously moved only on
algorithmic signals (promotion count, success count, time decay).
Add a channel for the owner to directly up- or down-vote any
memory so the system's priorities align with their taste:

    shopai feedback <memory_id> +1 "great scale call, saved me $50"
    shopai feedback <memory_id> -1 "ignored context"

Effects:

  1. Score adjustment — up-votes lift the memory's score by ``+_UP_STEP``
     (capped at 5.0); down-votes lower by ``-_DOWN_STEP`` (floor 1.0).
  2. Feedback event — a ``category=feedback score=4.5`` memory is
     written with the original memory id + sign + note, so the
     brain knows *why* it was corrected and can retrieve other
     feedback later.
  3. Threshold prior — aggregated up/down counts become a prior
     for the pre-launch predictor (D2-v1): launches whose features
     look like ones the owner down-voted will score lower.

Single-file, no LLM — keeps the feedback loop cheap enough that
the owner can correct dozens of decisions per day.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")

_UP_STEP = 0.25        # small enough that a single vote doesn't dominate
_DOWN_STEP = 0.40      # down-votes carry more weight (negative is rarer)
_MIN_SCORE = 1.0
_MAX_SCORE = 5.0


@dataclass
class FeedbackResult:
    memory_id: int
    sign: int               # +1 or -1
    note: str
    prior_score: float
    new_score: float
    feedback_memory_id: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "sign": self.sign,
            "note": self.note,
            "prior_score": round(self.prior_score, 2),
            "new_score": round(self.new_score, 2),
            "feedback_memory_id": self.feedback_memory_id,
        }


def record(memory_id: int, sign: int, note: str = "") -> FeedbackResult:
    """Apply one owner vote to a memory. Never raises — missing rows
    return a result with ``feedback_memory_id=None`` and no score move."""
    sign = 1 if sign > 0 else (-1 if sign < 0 else 0)
    result = FeedbackResult(
        memory_id=int(memory_id), sign=sign, note=note or "",
        prior_score=0.0, new_score=0.0, feedback_memory_id=None,
    )
    if sign == 0 or not _DB_PATH.exists():
        return result

    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT score FROM memories WHERE id=?", (int(memory_id),))
        row = cur.fetchone()
        if not row:
            return result
        prior = float(row[0] or 0)
        delta = _UP_STEP if sign > 0 else -_DOWN_STEP
        new_score = max(_MIN_SCORE, min(_MAX_SCORE, prior + delta))
        cur.execute(
            "UPDATE memories SET score=?, last_updated=? WHERE id=?",
            (new_score, time.time(), int(memory_id)),
        )
        conn.commit()
        result.prior_score = prior
        result.new_score = new_score
    finally:
        conn.close()

    # Write the feedback as its own memory so retrieval can learn
    # from the pattern of corrections.
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        fid = mi.create(
            category="feedback",
            content={
                "target_memory_id": int(memory_id),
                "sign": sign,
                "note": note[:400],
                "prior_score": result.prior_score,
                "new_score": result.new_score,
            },
            action="up_vote" if sign > 0 else "down_vote",
            score=4.5,
            tags=[
                "feedback",
                "owner",
                "up" if sign > 0 else "down",
                f"memory:{memory_id}",
            ],
        )
        result.feedback_memory_id = int(fid) if fid else None
    except Exception:
        pass

    return result


@dataclass
class FeedbackSummary:
    total: int = 0
    up_votes: int = 0
    down_votes: int = 0
    categories_up: dict[str, int] = None
    categories_down: dict[str, int] = None

    def __post_init__(self) -> None:
        if self.categories_up is None:
            self.categories_up = {}
        if self.categories_down is None:
            self.categories_down = {}


def summarise() -> FeedbackSummary:
    """Roll up owner feedback by target memory category. Used by the
    predictor to nudge launches away from down-voted feature clusters."""
    summary = FeedbackSummary()
    if not _DB_PATH.exists():
        return summary
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories WHERE category='feedback'"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # Build a second map: target memory id → its category
    ids = []
    for (content_json,) in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        ids.append((int(c.get("target_memory_id") or 0), int(c.get("sign") or 0)))
    if not ids:
        return summary
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, category FROM memories WHERE id IN ({})".format(
                ",".join("?" * len(ids))
            ),
            [mid for mid, _ in ids],
        )
        cat_by_id = {mid: cat for mid, cat in cur.fetchall()}
    finally:
        conn.close()

    for mid, sign in ids:
        if mid not in cat_by_id:
            continue
        cat = cat_by_id[mid]
        summary.total += 1
        if sign > 0:
            summary.up_votes += 1
            summary.categories_up[cat] = summary.categories_up.get(cat, 0) + 1
        elif sign < 0:
            summary.down_votes += 1
            summary.categories_down[cat] = summary.categories_down.get(cat, 0) + 1
    return summary
