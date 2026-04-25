"""Pre-launch success predictor.

Before the pipeline burns the 5-15 seconds on Shopify + Meta Ads, we
grade the proposed launch against past outcomes and return a
``win_probability`` in [0, 1] plus a short rationale. Owners can
abort low-probability launches (``shopai launch --min-win-prob 0.5``).

Signals used (all deterministic, no LLM):

  1. Semantic match to proven launches — pull top-K launches from the
     semantic index, weight by their realised ROAS (if known), average
     cosine × normalised_roas. More similar to a winner → higher score.
  2. Niche priors — look at all past launches tagged in the same niche,
     compute the fraction that reached ``verdict='scale'``.
  3. Price positioning — launches with target_price > supplier_cost *
     (1 + margin_floor) historically convert better; reject the extremes.
  4. Copy-tone prior — if a tone has > N samples, use its historical
     success rate; otherwise cede to the niche prior.

Weights are hand-tuned on day-one and live in a single ``_WEIGHTS``
dict; Day-4 self-critique will let the brain re-tune them itself.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("autonomous.launch_predictor")


_DB_PATH = Path("data/memory_intelligence.db")
_EPS = 1e-6


_WEIGHTS = {
    "semantic": 0.40,
    "niche_prior": 0.25,
    "price_fit": 0.15,
    "tone_prior": 0.10,
    "baseline": 0.10,  # soft floor so brand-new stores don't score 0
}


@dataclass
class Prediction:
    win_probability: float
    grade: str                       # A / B / C / D
    rationale: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    similar_launches: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "win_probability": round(self.win_probability, 3),
            "grade": self.grade,
            "rationale": self.rationale,
            "signals": {k: round(v, 3) for k, v in self.signals.items()},
            "similar_launches": self.similar_launches[:5],
        }


def predict(goal: Any) -> Prediction:
    """Score a :class:`workflows.launch.context.LaunchGoal` before
    running the pipeline. Never raises — degenerate inputs return
    the baseline (0.5) so owner can still proceed."""
    rationale: list[str] = []
    signals: dict[str, float] = {}

    # Resolve the text we'll embed to find similar past launches
    source_title, supplier_price = _source_text_and_price(goal)
    niche = (getattr(goal, "niche", "") or "").lower().strip()
    tone = getattr(goal, "copy_tone", "friendly") or "friendly"
    target_price = float(getattr(goal, "target_price", 0) or 0)

    # ── 1. Semantic match to past launches ─────────────────
    sem_score, similar = _semantic_score(source_title, niche)
    signals["semantic"] = sem_score
    if similar:
        rationale.append(
            f"{len(similar)} semantically-similar past launches "
            f"(top cosine {similar[0]['score']:.2f})"
        )
    else:
        rationale.append("no semantic matches — brand-new concept")

    # ── 2. Niche prior ─────────────────────────────────────
    niche_score, niche_evidence = _niche_prior(niche)
    signals["niche_prior"] = niche_score
    if niche_evidence:
        rationale.append(
            f"niche '{niche}' success rate {niche_score:.0%} "
            f"over {niche_evidence} past launches"
        )

    # ── 3. Price fit ───────────────────────────────────────
    price_score, price_note = _price_fit(supplier_price, target_price,
                                         getattr(goal, "margin_floor", 0.3))
    signals["price_fit"] = price_score
    if price_note:
        rationale.append(price_note)

    # ── 4. Tone prior ──────────────────────────────────────
    tone_score, tone_evidence = _tone_prior(tone)
    signals["tone_prior"] = tone_score
    if tone_evidence:
        rationale.append(
            f"tone '{tone}' success rate {tone_score:.0%} "
            f"over {tone_evidence} past launches"
        )

    # ── 5. Combine ─────────────────────────────────────────
    signals["baseline"] = 0.5
    total = sum(
        signals[name] * _WEIGHTS[name] for name in _WEIGHTS
    )
    total = max(0.0, min(1.0, total))

    return Prediction(
        win_probability=total,
        grade=_grade_for(total),
        rationale=rationale,
        signals=signals,
        similar_launches=similar,
    )


# ── Signal computations ──────────────────────────────────────

def _source_text_and_price(goal: Any) -> tuple[str, float]:
    payload = getattr(goal, "manual_payload", None) or {}
    title = payload.get("title") or getattr(goal, "alibaba_url", "") or ""
    price = float(payload.get("price_usd") or 0)
    return title, price


def _semantic_score(title: str, niche: str) -> tuple[float, list[dict[str, Any]]]:
    """Average cosine of top-K launches weighted by realised ROAS.
    When ROAS isn't known yet the launch contributes at 0.5 (neutral)."""
    if not title and not niche:
        return 0.5, []
    try:
        from core.memory.semantic_index import retrieve_similar
    except Exception:
        return 0.5, []
    query = f"{title} {niche}".strip()
    hits = retrieve_similar(query, k=5, level_min=0, category="launch")
    if not hits:
        return 0.5, []
    weighted = 0.0
    total_w = 0.0
    out: list[dict[str, Any]] = []
    for h in hits:
        roas_weight = _roas_weight_for_launch(h["memory"].get("id"))
        weighted += h["score"] * roas_weight
        total_w += abs(h["score"])
        out.append({
            "memory_id": h["id"],
            "score": round(h["score"], 3),
            "roas_weight": round(roas_weight, 3),
        })
    if total_w < _EPS:
        return 0.5, out
    # Map weighted average in [-1, 1] → [0, 1]
    norm = (weighted / total_w + 1) / 2.0
    return max(0.0, min(1.0, norm)), out


def _roas_weight_for_launch(memory_id: int | None) -> float:
    """Return a [0, 1] weight reflecting how well the launch performed.
    Default 0.5 when outcome data isn't available yet."""
    if not memory_id:
        return 0.5
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
    except Exception:
        return 0.5
    # Map every evaluator bucket back to a scalar weight
    for s in report.scale_recommendations:
        if s.shopify_product_id is None:
            continue
        if _memory_points_at_launch(memory_id, s.launch_id):
            return 1.0
    for s in report.kill_recommendations:
        if _memory_points_at_launch(memory_id, s.launch_id):
            return 0.0
    return 0.5


def _memory_points_at_launch(memory_id: int, launch_id: str) -> bool:
    """Return True when the memory row's content references the
    launch id (quick SQL lookup)."""
    if not _DB_PATH.exists():
        return False
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT content FROM memories WHERE id=?", (int(memory_id),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return False
    try:
        content = json.loads(row[0] or "{}")
    except (json.JSONDecodeError, ValueError):
        return False
    return content.get("launch_id") == launch_id


def _niche_prior(niche: str) -> tuple[float, int]:
    if not niche or not _DB_PATH.exists():
        return 0.5, 0
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories WHERE category='launch' AND tags LIKE ?",
            (f"%{niche}%",),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return 0.5, 0
    # Approximate: launches that have an order_count > 0 count as wins
    wins = 0
    for r in rows:
        try:
            c = json.loads(r[0] or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        if c.get("verdict") == "scale":
            wins += 1
    rate = wins / len(rows) if rows else 0.5
    # Add small-sample correction so 1/1 doesn't claim 100 %
    rate = (wins + 1) / (len(rows) + 2)
    return rate, len(rows)


def _price_fit(supplier: float, target: float, floor: float) -> tuple[float, str]:
    if supplier <= 0 or target <= 0:
        return 0.5, ""
    required_floor = supplier * (1 + floor)
    margin = (target - supplier) / target
    if target < required_floor:
        return 0.1, f"target ${target:.2f} below margin floor ${required_floor:.2f}"
    if margin > 0.85:
        return 0.35, f"margin {margin:.0%} > 85 % — likely unsellable price ({target:.2f})"
    if 0.40 <= margin <= 0.75:
        return 0.9, f"margin {margin:.0%} in sweet spot (40-75 %)"
    return 0.65, f"margin {margin:.0%} acceptable"


def _tone_prior(tone: str) -> tuple[float, int]:
    if not tone or not _DB_PATH.exists():
        return 0.5, 0
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories WHERE category='launch' AND content LIKE ?",
            (f'%"copy_tone":"{tone}"%',),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return 0.5, 0
    wins = 0
    for r in rows:
        try:
            c = json.loads(r[0] or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        if c.get("verdict") == "scale":
            wins += 1
    rate = (wins + 1) / (len(rows) + 2)
    return rate, len(rows)


def _grade_for(p: float) -> str:
    if p >= 0.75:
        return "A"
    if p >= 0.6:
        return "B"
    if p >= 0.45:
        return "C"
    return "D"
