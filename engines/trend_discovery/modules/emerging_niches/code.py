"""Emerging niches discovery — detect new niches before they go mainstream.

Identifies niches forming from weak signals across multiple data sources:
  - Low search volume but high growth rate (>100% YoY)
  - Cross-references search + social + patents + funding signals
  - Scores niche emergence maturity (pre-market, early, growing, mainstream)
  - Identifies trigger events (regulation, technology, cultural shift)

Input: {data: {signals, category, trigger_filter, min_viability, scan_known}}
Output: {status, data, meta, error} — engine contract
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data import SIGNAL_WEIGHTS, KNOWN_EMERGING_NICHES, NICHE_LIFECYCLE_STAGES
from .logic import assess_niche_viability, estimate_niche_timeline, recommend_entry_timing
from .rules import evaluate_niche_rules


def discover_emerging_niches(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Main niche discovery — engine contract."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    candidates = _gather_candidates(data)
    scored = _score_candidates(candidates, data)
    results = _build_results(scored, data)

    output_check = _validate_output(results)
    if not output_check["valid"]:
        return _error_output(output_check["reason"])

    return {
        "status": "success",
        "data": results,
        "meta": {
            "engine": "emerging_niches",
            "confidence": _confidence(scored),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidates_evaluated": len(candidates),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate input conforms to engine contract."""
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Input must be dict"}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Input.data must be dict"}
    if not (data.get("signals") or data.get("category") or data.get("scan_known", False)):
        return {"valid": False, "reason": "Need signals, category, or scan_known=True"}
    return {"valid": True, "reason": "OK"}


def _gather_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Gather niche candidates from input signals and known niches database."""
    candidates: list[dict[str, Any]] = []

    # Include user-provided signals as custom candidates
    user_signals = data.get("signals", [])
    if isinstance(user_signals, list):
        for sig in user_signals:
            if isinstance(sig, dict) and sig.get("name"):
                candidates.append({
                    "name": sig["name"],
                    "maturity": sig.get("maturity", "pre-market"),
                    "signals": sig.get("signals", {}),
                    "trigger": sig.get("trigger", "unknown"),
                    "description": sig.get("description", ""),
                    "source": "user_input",
                })

    # Optionally include known emerging niches database
    if data.get("scan_known", True):
        trigger_filter = data.get("trigger_filter")
        maturity_filter = data.get("maturity_filter")

        for niche in KNOWN_EMERGING_NICHES:
            if trigger_filter and niche["trigger"] != trigger_filter:
                continue
            if maturity_filter and niche["maturity"] != maturity_filter:
                continue
            candidates.append({**niche, "source": "database"})

    return candidates


def _score_candidates(candidates: list[dict[str, Any]],
                      data: dict[str, Any]) -> list[dict[str, Any]]:
    """Score each candidate niche for viability, timeline, and rules compliance."""
    min_viability = data.get("min_viability", 0)
    scored: list[dict[str, Any]] = []

    for candidate in candidates:
        viability = assess_niche_viability(candidate)
        timeline = estimate_niche_timeline(candidate)
        rules = evaluate_niche_rules(candidate)
        entry = recommend_entry_timing(candidate)

        composite = _composite_niche_score(candidate, viability)

        if composite < min_viability:
            continue

        scored.append({
            "name": candidate["name"],
            "description": candidate.get("description", ""),
            "maturity": candidate["maturity"],
            "trigger": candidate.get("trigger", "unknown"),
            "source": candidate.get("source", "unknown"),
            "composite_score": composite,
            "viability": viability,
            "timeline": timeline,
            "entry_timing": entry,
            "rules_check": rules,
        })

    scored.sort(key=lambda n: n["composite_score"], reverse=True)
    return scored


def _composite_niche_score(candidate: dict[str, Any],
                           viability: dict[str, Any]) -> int:
    """Compute a single composite score (0-100) combining viability and opportunity."""
    viability_score = viability.get("viability_score", 0)
    maturity = candidate.get("maturity", "pre-market")

    # Earlier maturity = higher opportunity multiplier (if viable)
    maturity_bonus = {"pre-market": 15, "early": 10, "growing": 5, "mainstream": -10}
    bonus = maturity_bonus.get(maturity, 0)

    # Signal momentum — higher average signals = stronger niche
    signals = candidate.get("signals", {})
    active = [v for v in signals.values() if v and v > 0]
    avg_signal = sum(active) / max(len(active), 1)
    momentum_bonus = min(15, avg_signal / 5)

    return max(0, min(100, round(viability_score + bonus + momentum_bonus)))


def _build_results(scored: list[dict[str, Any]],
                   data: dict[str, Any]) -> dict[str, Any]:
    """Assemble final results payload with categorized niche lists."""
    max_results = data.get("max_results", 10)
    top_niches = scored[:max_results]

    enter_now = [n for n in top_niches if n["entry_timing"]["timing"] == "enter_now"]
    watch_list = [n for n in top_niches
                  if n["entry_timing"]["timing"] in ("wait_3_months", "wait_6_months")]

    return {
        "total_evaluated": len(scored),
        "top_niches": top_niches,
        "enter_now": enter_now,
        "watch_list": watch_list,
        "maturity_breakdown": _maturity_breakdown(scored),
        "recommendation": _overall_recommendation(enter_now, watch_list, scored),
    }


def _maturity_breakdown(scored: list[dict[str, Any]]) -> dict[str, int]:
    """Count niches by maturity stage."""
    counts: dict[str, int] = {"pre-market": 0, "early": 0, "growing": 0, "mainstream": 0}
    for n in scored:
        stage = n.get("maturity", "pre-market")
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _overall_recommendation(enter_now: list, watch_list: list,
                            all_scored: list) -> str:
    """Generate a top-level recommendation based on scored niches."""
    if len(enter_now) >= 3:
        return "Multiple strong niches identified — pick top 1-2 and validate with $200 test"
    if len(enter_now) >= 1:
        return (f"{len(enter_now)} niche ready for entry — "
                "run validation playbook before committing inventory")
    if len(watch_list) >= 2:
        return "No niches ready yet — add watch list to monthly review cycle"
    if len(all_scored) > 0:
        return "Weak signals only — expand signal sources and re-scan in 4 weeks"
    return "No emerging niches detected — broaden category scope or check signal inputs"


def _confidence(scored: list[dict[str, Any]]) -> float:
    """Calculate confidence level based on quantity and quality of scored niches."""
    if not scored:
        return 0.1
    avg_viability = sum(n["composite_score"] for n in scored) / len(scored)
    diversity = min(1.0, len(scored) / 8)
    return round(min(0.95, 0.2 + (avg_viability / 200) + diversity * 0.3), 2)


def _validate_output(data: dict[str, Any]) -> dict[str, Any]:
    """Validate output conforms to engine contract."""
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Output must be dict"}
    if "top_niches" not in data:
        return {"valid": False, "reason": "Missing top_niches"}
    return {"valid": True, "reason": "OK"}


def _error_output(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": "emerging_niches",
            "confidence": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": {"reason": reason},
    }
