"""Curiosity-driven exploration — ε-greedy over untried combinations.

Every subsystem built so far biases toward *exploit*: the best rule,
the highest-confidence skill, the proven transfer strategy. That's
the right default, but a store that never explores converges to a
local maximum. Sprint v3-D2 imitation captures owner preferences;
transfer learning (v3-D6) generalises wins. But neither *proposes*
untried permutations — you only learn what you sample.

This module enumerates the feature space the launch pipeline
actually varies (copy_tone × price_band × niche × primary_quality_
band) and tracks which cells the brain has already explored. An
ε-greedy policy decides each cycle whether to exploit the best-
known cell (1 − ε) or fire a curiosity probe at the least-explored
cell (ε, default 0.15).

Output is an ``ExplorationHint`` the planner + owner digest (v2-D6)
can quote: "try a luxury-tone × premium-band launch — 0 prior
samples." Emits ``category=exploration score=3.5`` memory events so
the brain logs every probe even if the launch later fails.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")

_TONES = ("urgent", "friendly", "luxury", "informative")
_PRICE_BANDS = ("impulse", "mid", "premium")
_QUALITY_BANDS = ("weak", "ok", "excellent")

_DEFAULT_EPSILON = 0.15


@dataclass
class FeatureCell:
    tone: str
    price_band: str
    quality_band: str
    samples: int = 0
    wins: int = 0

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.tone, self.price_band, self.quality_band)

    @property
    def novelty(self) -> float:
        """Inverse-log novelty. 0 samples → 1.0; more samples → <= 0."""
        return 1.0 / math.log(2.0 + self.samples)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tone": self.tone,
            "price_band": self.price_band,
            "quality_band": self.quality_band,
            "samples": self.samples,
            "wins": self.wins,
            "novelty": round(self.novelty, 3),
        }


@dataclass
class ExplorationHint:
    mode: str                     # "exploit" | "explore"
    cell: FeatureCell
    rationale: str
    epsilon: float
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cell": self.cell.as_dict(),
            "rationale": self.rationale,
            "epsilon": self.epsilon,
            "ts": self.ts,
        }


def suggest(epsilon: float | None = None, seed: int | None = None) -> ExplorationHint:
    """Return one hint. With probability epsilon fire a curiosity
    probe at the least-explored cell; otherwise exploit the cell
    with the highest win rate."""
    eps = _DEFAULT_EPSILON if epsilon is None else float(epsilon)
    eps = max(0.0, min(1.0, eps))
    if seed is not None:
        random.seed(seed)

    cells = _build_space()
    if not cells:
        return _blank(eps)
    _populate_samples(cells)

    should_explore = random.random() < eps
    if should_explore:
        novel = min(cells, key=lambda c: c.samples)
        hint = ExplorationHint(
            mode="explore",
            cell=novel,
            epsilon=eps,
            rationale=(
                f"ε-greedy probe: cell has {novel.samples} prior "
                f"samples — least-explored bucket in the space"
            ),
            ts=time.time(),
        )
    else:
        exploit = max(
            (c for c in cells if c.samples > 0),
            key=lambda c: c.wins / (c.samples + 1e-6),
            default=None,
        )
        if exploit is None:
            exploit = random.choice(cells)
        hint = ExplorationHint(
            mode="exploit",
            cell=exploit,
            epsilon=eps,
            rationale=(
                f"exploit: {exploit.wins}/{exploit.samples} wins "
                f"({exploit.wins / max(1, exploit.samples):.0%} base rate)"
            ),
            ts=time.time(),
        )
    _persist(hint)
    return hint


def stats() -> dict[str, Any]:
    """Summarise coverage of the feature space."""
    cells = _build_space()
    _populate_samples(cells)
    explored = sum(1 for c in cells if c.samples > 0)
    return {
        "total_cells": len(cells),
        "explored_cells": explored,
        "coverage": round(explored / len(cells), 3) if cells else 0.0,
        "top_novel": [
            c.as_dict()
            for c in sorted(cells, key=lambda x: x.samples)[:5]
        ],
    }


# ── Internals ───────────────────────────────────────────────

def _build_space() -> list[FeatureCell]:
    return [
        FeatureCell(tone=t, price_band=pb, quality_band=qb)
        for t in _TONES for pb in _PRICE_BANDS for qb in _QUALITY_BANDS
    ]


def _populate_samples(cells: list[FeatureCell]) -> None:
    """Count past launch events per feature cell from memory. Also
    count wins (evaluator verdict=scale)."""
    if not _DB_PATH.exists():
        return
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories "
            "WHERE category='launch' ORDER BY timestamp DESC LIMIT 500",
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # Index cells by key for O(1) lookup
    index = {c.key: c for c in cells}
    for (content_json,) in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        tone = (c.get("copy_tone") or "").strip().lower()
        pb = _price_band(c.get("target_price") or 0)
        qb = _quality_band(c.get("primary_quality") or 0)
        cell = index.get((tone, pb, qb))
        if cell is None:
            continue
        cell.samples += 1
        if c.get("verdict") == "scale":
            cell.wins += 1


def _price_band(p: float) -> str:
    p = float(p or 0)
    if p >= 80:
        return "premium"
    if p >= 25:
        return "mid"
    return "impulse"


def _quality_band(q: int) -> str:
    q = int(q or 0)
    if q >= 80:
        return "excellent"
    if q >= 60:
        return "ok"
    return "weak"


def _persist(hint: ExplorationHint) -> None:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="exploration",
            content=hint.as_dict(),
            action=hint.mode,
            score=3.5,
            tags=["exploration", hint.mode,
                  hint.cell.tone, hint.cell.price_band,
                  hint.cell.quality_band],
        )
    except Exception:
        pass


def _blank(eps: float) -> ExplorationHint:
    fallback = FeatureCell(
        tone="friendly", price_band="mid", quality_band="ok",
    )
    return ExplorationHint(
        mode="exploit", cell=fallback, epsilon=eps,
        rationale="(no feature space populated yet)",
        ts=time.time(),
    )
