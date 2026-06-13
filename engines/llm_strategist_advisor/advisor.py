"""Deterministic baseline + LLM-refined pattern surfacing."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    signal: str
    positive_count: int
    negative_count: int
    unknown_count: int
    total: int
    success_rate: float = 0.0
    confidence: str = "low"   # low / medium / high
    rank: int = 0
    pattern_insight: str = ""


@dataclass
class AdvisorReport:
    store_id: str
    k: int
    entries_scanned: int = 0
    recommendations: list[Recommendation] = field(
        default_factory=list,
    )
    llm_used: bool = False
    llm_reason: str = ""


def _is_test_environment() -> bool:
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _ai_enabled() -> bool:
    return bool(os.environ.get("SHOPAI_AI_STRATEGY"))


def _confidence_band(sample_size: int) -> str:
    if sample_size >= 10:
        return "high"
    if sample_size >= 3:
        return "medium"
    return "low"


def _deterministic_baseline(
    entries: list[dict[str, Any]], store_id: str, k: int,
) -> list[Recommendation]:
    """Group by signal; rank by positive_count desc."""
    by_signal: dict[
        str, dict[str, int],
    ] = {}
    for e in entries:
        sig = str(e.get("signal") or "")
        if not sig:
            continue
        bucket = by_signal.setdefault(sig, {
            "positive": 0,
            "negative": 0,
            "unknown": 0,
        })
        outcome = str(e.get("outcome") or "unknown")
        if outcome in bucket:
            bucket[outcome] += 1
        else:
            bucket["unknown"] += 1

    recs: list[Recommendation] = []
    for sig, counts in by_signal.items():
        total = (
            counts["positive"]
            + counts["negative"]
            + counts["unknown"]
        )
        if total == 0:
            continue
        decided = counts["positive"] + counts["negative"]
        sr = (
            counts["positive"] / decided
            if decided > 0 else 0.0
        )
        recs.append(Recommendation(
            signal=sig,
            positive_count=counts["positive"],
            negative_count=counts["negative"],
            unknown_count=counts["unknown"],
            total=total,
            success_rate=round(sr, 3),
            confidence=_confidence_band(decided),
        ))
    # Rank: positive_count desc, then success_rate desc
    recs.sort(
        key=lambda r: (
            r.positive_count, r.success_rate,
        ),
        reverse=True,
    )
    for i, r in enumerate(recs[:max(1, k)]):
        r.rank = i + 1
    return recs[:max(1, k)]


def _build_prompt(
    store_id: str,
    recs: list[Recommendation],
) -> tuple[str, str]:
    system = (
        "You are an e-commerce strategist analysing a "
        "Shopify store's autonomous action history. You "
        "will be given a deterministic ranking of action "
        "signals and their outcome counts. Your job is "
        "to OPTIONALLY add a one-sentence pattern_insight "
        "to each entry — a qualitative observation an "
        "operator would find useful. Do NOT reorder, "
        "invent signals, or change any numeric fields. "
        "Return JSON {\"insights\": [{\"signal\": str, "
        "\"insight\": str}]} only."
    )
    lines = [
        f"Store: {store_id or '(fleet)'}",
        "Ranked signals (most successful first):",
    ]
    for r in recs:
        lines.append(
            f"  - {r.signal}: positive={r.positive_count}, "
            f"negative={r.negative_count}, "
            f"unknown={r.unknown_count}, "
            f"success_rate={r.success_rate}, "
            f"confidence={r.confidence}"
        )
    user = "\n".join(lines)
    return system, user


def _refine_with_llm(
    recs: list[Recommendation],
    store_id: str,
) -> tuple[list[Recommendation], bool, str]:
    """Returns (recs, llm_used, reason)."""
    if not _ai_enabled():
        return recs, False, "SHOPAI_AI_STRATEGY not set"
    if _is_test_environment():
        return recs, False, "pytest guard"
    try:
        from engines._ai_strategies import _LLMClient
    except Exception as exc:  # noqa: BLE001
        return recs, False, f"client import failed: {exc}"
    client = _LLMClient()
    if not client.available:
        return recs, False, "no LLM client available"
    if not recs:
        return recs, False, "no recommendations to refine"
    system, user = _build_prompt(store_id, recs)
    try:
        parsed = client.chat_json(system, user)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "llm_strategist: chat raised: %s", exc,
        )
        return recs, False, f"chat raised: {exc}"
    if not isinstance(parsed, dict):
        return recs, False, "non-dict response"
    insights = parsed.get("insights")
    if not isinstance(insights, list):
        return recs, False, "missing insights list"
    by_sig: dict[str, str] = {}
    for item in insights:
        if not isinstance(item, dict):
            continue
        sig = str(item.get("signal") or "")
        ins = str(item.get("insight") or "")
        if sig and ins:
            by_sig[sig] = ins
    for r in recs:
        if r.signal in by_sig:
            r.pattern_insight = by_sig[r.signal][:240]
    return recs, True, "ok"


def advise(
    *,
    store_id: str = "",
    signal: str = "",
    k: int = 10,
    entries_override: list[dict[str, Any]] | None = None,
) -> AdvisorReport:
    """Build the consultant-pattern advisor report."""
    report = AdvisorReport(
        store_id=store_id, k=max(1, k),
    )
    if entries_override is not None:
        entries = list(entries_override)
    else:
        try:
            from engines.strategist_memory.store import (
                recall,
            )
            entries = recall(
                store_id=store_id, signal=signal,
                k=max(k * 10, 100),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "llm_strategist: recall raised: %s", exc,
            )
            entries = []
    report.entries_scanned = len(entries)

    recs = _deterministic_baseline(
        entries, store_id=store_id, k=report.k,
    )
    recs, used, reason = _refine_with_llm(
        recs, store_id=store_id,
    )
    report.recommendations = recs
    report.llm_used = used
    report.llm_reason = reason
    return report
