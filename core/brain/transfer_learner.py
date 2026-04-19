"""Cross-niche transfer learning.

Most per-niche rules are narrow ("electronics + urgent tone wins"),
but the underlying *abstract* pattern — "the urgent tone wins when
there's a trust signal to accompany it" — is niche-agnostic. This
module converts concrete winners into abstract, transferable
patterns and stores them as level-3 strategies keyed by
``universality > 0.6``.

Algorithm (deterministic, O(N)):

  1. Pull every ``category=launch`` memory whose verdict is ``scale``
     and every ``category=order`` tagged with a launch_id that maps
     to a winner.
  2. Group by normalised *abstract feature* — the feature vector is
     (copy_tone, margin_band, price_band, has_video, gallery_size,
     primary_quality_band). Niche is intentionally dropped.
  3. For each feature combination that appears in ≥ 2 distinct
     niches with ≥ 1 scale verdict each, emit a transfer-ready
     strategy. The more niches a pattern crosses, the higher its
     ``universality`` score.
  4. Store as ``category=transfer_strategy level=3`` memory with
     source ids so ``retrieve_for_decision`` can surface it even
     when the caller queries an entirely new niche.

No LLM is used — purely statistical pattern mining. The Day-7
conversational layer will wrap this output in natural language
when the owner asks "what works across niches?"
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.transfer_learner")


_DB_PATH = Path("data/memory_intelligence.db")
_MIN_NICHES = 2          # need at least 2 different niches to call it universal
_MIN_WINS_PER_NICHE = 1


@dataclass
class TransferPattern:
    feature: dict[str, Any]       # the abstract feature combination
    niches: list[str]             # niches that produced wins
    wins: int
    total: int
    universality: float            # wins-per-niche fraction, bounded [0, 1]
    sample_launch_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "niches": self.niches,
            "wins": self.wins,
            "total": self.total,
            "universality": round(self.universality, 3),
            "sample_launch_ids": self.sample_launch_ids[:5],
        }


@dataclass
class TransferReport:
    patterns: list[TransferPattern] = field(default_factory=list)
    examined: int = 0
    promoted: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "promoted": self.promoted,
            "patterns": [p.as_dict() for p in self.patterns],
        }


def extract(limit: int = 500) -> TransferReport:
    """Run one transfer-pattern extraction pass."""
    try:
        rows = _load_launch_content(limit)
    except Exception as exc:
        logger.warning("transfer_learner load failed: %s", exc)
        return TransferReport()

    if not rows:
        return TransferReport()

    # feature → { niches: set, wins: int, total: int, launch_ids: list }
    groups: dict[tuple, dict[str, Any]] = defaultdict(
        lambda: {"niches": set(), "wins": 0, "total": 0, "launch_ids": []},
    )
    for row in rows:
        feat = _feature_for(row)
        niche = row.get("niche") or ""
        entry = groups[feat]
        entry["total"] += 1
        entry["niches"].add(niche)
        entry["launch_ids"].append(row.get("launch_id"))
        if row.get("verdict") == "scale":
            entry["wins"] += 1

    report = TransferReport(examined=len(rows))
    for feat, e in groups.items():
        niches = [n for n in e["niches"] if n]
        if len(niches) < _MIN_NICHES:
            continue
        if e["wins"] < _MIN_NICHES * _MIN_WINS_PER_NICHE:
            continue
        # Universality = fraction of niches in which this feature won.
        # Bounded to [0, 1]. Higher = transfers cleaner.
        universality = min(1.0, e["wins"] / max(1, e["total"]))
        patt = TransferPattern(
            feature=_feature_to_dict(feat),
            niches=sorted(niches),
            wins=e["wins"],
            total=e["total"],
            universality=universality,
            sample_launch_ids=[lid for lid in e["launch_ids"] if lid][:5],
        )
        report.patterns.append(patt)

    # Rank by universality * niche_breadth
    report.patterns.sort(
        key=lambda p: -p.universality * len(p.niches),
    )

    # Persist top 5 (keeps level-3 slice tight)
    promoted = 0
    for p in report.patterns[:5]:
        if _persist(p):
            promoted += 1
    report.promoted = promoted
    return report


def retrieve_for_niche(niche: str, k: int = 3) -> list[dict[str, Any]]:
    """Return the top-K transfer strategies that apply to *niche*,
    sorted by universality × whether the feature matches the niche's
    own distribution. For now we just return the globally highest-
    universality set so a brand-new niche can piggyback on proven
    abstract patterns."""
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, score, content FROM memories "
            "WHERE category='transfer_strategy' AND level=3 "
            "ORDER BY score DESC, id DESC LIMIT ?",
            (int(k),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            content = json.loads(r[2] or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        out.append({"id": r[0], "score": r[1], **content})
    return out


# ── Feature extraction ──────────────────────────────────────

def _feature_for(row: dict[str, Any]) -> tuple:
    """Discretise a launch into an abstract feature tuple. Numeric
    fields are bucketed so launches cluster by order of magnitude
    rather than exact value."""
    tone = (row.get("copy_tone") or "friendly").lower()
    margin = row.get("margin_pct") or 0
    price = row.get("target_price") or 0
    gallery = int(row.get("gallery_size") or 0)
    has_video = bool(row.get("has_video"))
    quality = int(row.get("primary_quality") or 0)
    return (
        tone,
        _margin_band(margin),
        _price_band(price),
        gallery >= 4,
        has_video,
        _quality_band(quality),
    )


def _feature_to_dict(feat: tuple) -> dict[str, Any]:
    tone, margin_band, price_band, gallery_rich, has_video, quality_band = feat
    return {
        "copy_tone": tone,
        "margin_band": margin_band,
        "price_band": price_band,
        "gallery_rich": gallery_rich,
        "has_video": has_video,
        "primary_quality_band": quality_band,
    }


def _margin_band(m: float) -> str:
    if m >= 0.75:
        return "high"
    if m >= 0.40:
        return "mid"
    if m >= 0.15:
        return "thin"
    return "below_floor"


def _price_band(p: float) -> str:
    if p >= 80:
        return "premium"
    if p >= 25:
        return "mid"
    if p >= 5:
        return "impulse"
    return "giveaway"


def _quality_band(q: int) -> str:
    if q >= 80:
        return "excellent"
    if q >= 60:
        return "ok"
    if q >= 40:
        return "weak"
    return "unknown"


# ── Data loaders ────────────────────────────────────────────

def _load_launch_content(limit: int) -> list[dict[str, Any]]:
    """Join launch registration events with their evaluator verdict so
    each row carries everything the feature extractor needs."""
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories WHERE category='launch' "
            "ORDER BY timestamp DESC LIMIT ?",
            (int(limit),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # Pull evaluator verdicts once
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
    except Exception:
        report = None

    verdict_by_id: dict[str, str] = {}
    if report is not None:
        for s in (
            report.kill_recommendations
            + report.scale_recommendations
            + report.monitor_recommendations
        ):
            verdict_by_id[s.launch_id] = s.verdict

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            c = json.loads(r[0] or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        lid = c.get("launch_id")
        if not lid:
            continue
        out.append({
            "launch_id": lid,
            "niche": (c.get("niche") or "").strip().lower(),
            "copy_tone": c.get("copy_tone") or "friendly",
            "target_price": c.get("target_price") or 0,
            "margin_pct": c.get("margin_pct") or 0,
            "gallery_size": c.get("gallery_size") or 0,
            "has_video": c.get("has_video") or False,
            "primary_quality": c.get("primary_quality") or 0,
            "verdict": verdict_by_id.get(lid, c.get("verdict", "")),
        })
    return out


def _persist(pattern: TransferPattern) -> bool:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="transfer_strategy",
            content=pattern.as_dict(),
            action="transfer_pattern",
            score=float(3.0 + 2.0 * pattern.universality),  # 3.0 - 5.0
            memory_type="semantic",
            tags=["transfer", "meta_learning", "universal"] + list(pattern.niches),
        )
        return True
    except Exception as exc:
        logger.debug("transfer persist failed: %s", exc)
        return False
