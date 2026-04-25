"""Analogical reasoning — "this is like X."

Humans solve novel problems by retrieving analogous past
situations and adapting their solutions. Neural-net retrievers do
this implicitly; ShopAI's structured features let us do it
explicitly, with transparent distance metrics the owner can audit.

API:
    analogies(target, k=3)
    analogise_launch(launch_id, k=3)

Each analogue carries:
  • source_id         — memory id of the analogous past launch
  • distance          — 0 = identical, ∞ = unrelated
  • shared_features   — which dimensions matched
  • differing_features — which dimensions did NOT match
  • outcome_hint      — what happened to the analogue (scale/kill/hold)
  • transferable      — True when the analogue reached a verdict
  • adaptation_hint   — concrete next-step derived from the analogue

Distance metric is a weighted Hamming over the v3-D6 transfer-
learner feature tuple (tone, margin_band, price_band, gallery_rich,
has_video, primary_quality_band), augmented with the niche label.
Each mismatched dimension adds a weight; niche mismatch is
down-weighted because cross-niche transfer patterns can still apply
(v3-D6).

Pure lookup over memory — no LLM. Sub-ms per query against a few
thousand launches.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")

# Weights for the Hamming distance. Lower = more forgiving mismatch.
_WEIGHTS = {
    "copy_tone":            1.2,
    "margin_band":          1.0,
    "price_band":           1.5,
    "gallery_rich":         0.6,
    "has_video":            0.5,
    "primary_quality_band": 0.8,
    "niche":                0.4,   # down-weighted: cross-niche ok
}


@dataclass
class Analogue:
    launch_id: str
    source_id: int
    distance: float
    shared_features: list[str]
    differing_features: list[str]
    outcome_hint: str
    transferable: bool
    adaptation_hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "source_id": self.source_id,
            "distance": round(self.distance, 3),
            "shared_features": self.shared_features,
            "differing_features": self.differing_features,
            "outcome_hint": self.outcome_hint,
            "transferable": self.transferable,
            "adaptation_hint": self.adaptation_hint,
        }


def analogies(target: dict[str, Any], k: int = 3) -> list[Analogue]:
    """Return the top-K most analogous past launches to *target*.

    ``target`` keys should include any of: copy_tone, margin_pct,
    target_price, gallery_size, has_video, primary_quality, niche.
    Missing keys are scored as mismatches against any value.
    """
    target_feat = _launch_to_feature(target)
    if not target_feat:
        return []

    candidates = _load_past_launches()
    scored: list[Analogue] = []
    verdict_by_id = _verdict_map()

    for row in candidates:
        cand_feat = _launch_to_feature(row)
        if not cand_feat:
            continue
        distance, shared, differing = _weighted_hamming(target_feat, cand_feat)
        lid = row.get("launch_id") or ""
        verdict = verdict_by_id.get(lid, row.get("verdict", ""))
        transferable = verdict in {"scale", "kill"}
        adaptation = _adaptation_hint(verdict, differing)
        scored.append(Analogue(
            launch_id=lid,
            source_id=int(row.get("id") or 0),
            distance=distance,
            shared_features=shared,
            differing_features=differing,
            outcome_hint=verdict or "unknown",
            transferable=transferable,
            adaptation_hint=adaptation,
        ))
    scored.sort(key=lambda a: (a.distance, -int(a.transferable)))
    return scored[:max(1, int(k))]


def analogise_launch(launch_id: str, k: int = 3) -> list[Analogue]:
    """Convenience: look up *launch_id* and find its analogues."""
    rows = _load_past_launches()
    target = next((r for r in rows
                   if (r.get("launch_id") or "") == launch_id), None)
    if target is None:
        return []
    return [a for a in analogies(target, k=k + 1)
            if a.launch_id != launch_id][:k]


# ── Internals ───────────────────────────────────────────────

def _launch_to_feature(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row:
        return None
    tone = (row.get("copy_tone") or "").lower() or None
    niche = (row.get("niche") or "").lower() or None
    margin = row.get("margin_pct")
    price = row.get("target_price") or row.get("sell_price")
    gallery = row.get("gallery_size") or 0
    has_video = bool(row.get("has_video"))
    quality = int(row.get("primary_quality") or 0)
    # Only emit a feature if at least one dimension is known
    if tone is None and price is None and niche is None:
        return None
    return {
        "copy_tone":            tone,
        "margin_band":          _margin_band(margin),
        "price_band":           _price_band(price),
        "gallery_rich":         gallery >= 4,
        "has_video":            has_video,
        "primary_quality_band": _quality_band(quality),
        "niche":                niche,
    }


def _margin_band(m: Any) -> str | None:
    try:
        m = float(m or 0)
    except (TypeError, ValueError):
        return None
    if m >= 0.75:
        return "high"
    if m >= 0.40:
        return "mid"
    if m >= 0.15:
        return "thin"
    if m > 0:
        return "below_floor"
    return None


def _price_band(p: Any) -> str | None:
    try:
        p = float(p or 0)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    if p >= 80:
        return "premium"
    if p >= 25:
        return "mid"
    if p >= 5:
        return "impulse"
    return "giveaway"


def _quality_band(q: int) -> str:
    q = int(q or 0)
    if q >= 80:
        return "excellent"
    if q >= 60:
        return "ok"
    if q >= 40:
        return "weak"
    return "unknown"


def _weighted_hamming(
    a: dict[str, Any], b: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    distance = 0.0
    shared: list[str] = []
    differing: list[str] = []
    for key, weight in _WEIGHTS.items():
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            # unknown on either side counts as a partial mismatch
            distance += weight * 0.5
            differing.append(key)
            continue
        if av == bv:
            shared.append(key)
        else:
            distance += weight
            differing.append(key)
    return distance, shared, differing


def _adaptation_hint(verdict: str, differing: list[str]) -> str:
    if verdict == "scale":
        diffs = ", ".join(differing[:3]) if differing else "no major differences"
        return (
            f"Past analogue reached SCALE. Keep matching dimensions; "
            f"differing dimensions to watch: {diffs}."
        )
    if verdict == "kill":
        diffs = ", ".join(differing[:3]) if differing else "(all same)"
        return (
            f"Past analogue was KILLED. Review differing dims "
            f"({diffs}) — the kill may replicate."
        )
    if verdict == "hold":
        return "Past analogue is holding — not enough data to copy."
    return "(analogue outcome unknown)"


def _load_past_launches() -> list[dict[str, Any]]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, content FROM memories "
            "WHERE category='launch' ORDER BY timestamp DESC LIMIT 500",
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for mid, content_json in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        c["id"] = int(mid)
        out.append(c)
    return out


def _verdict_map() -> dict[str, str]:
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for s in (
        report.kill_recommendations
        + report.scale_recommendations
        + report.monitor_recommendations
    ):
        out[s.launch_id] = s.verdict
    return out
