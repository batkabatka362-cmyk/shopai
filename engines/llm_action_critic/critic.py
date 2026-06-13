"""Deterministic critique + LLM rationale refinement."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Critique:
    rank: int
    action: str
    cli_command: str
    risk_flags: list[str] = field(default_factory=list)
    counter_rationale: str = ""
    severity: str = "info"   # critical / warn / info


@dataclass
class CritiqueReport:
    store_id: str
    verdict: str
    critiques: list[Critique] = field(default_factory=list)
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


# Anti-pattern catalogue: (substring trigger) -> flag list +
# counter rationale.
_ANTI_PATTERNS: dict[str, dict[str, Any]] = {
    "cycle run": {
        "flags": ["cycle_without_failure_check"],
        "rationale": (
            "Running another cycle without first checking "
            "shopai engine alerts can re-trigger a known "
            "failure class."
        ),
        "severity": "warn",
    },
    "earn-bootstrap": {
        "flags": ["credentials_required"],
        "rationale": (
            "Bootstrap needs valid Shopify credentials + "
            "store seed. Run shopai go-live first to "
            "confirm the gate."
        ),
        "severity": "warn",
    },
    "batch-review --auto-approve-ok": {
        "flags": ["wide_blast_radius"],
        "rationale": (
            "Batch-approve commits N actions at once. "
            "If consensus picked a bad action, blast "
            "radius is N stores. Consider --dry-run first."
        ),
        "severity": "warn",
    },
    "spend-status": {
        "flags": ["check_pending_ads_first"],
        "rationale": (
            "Tightening spend caps mid-flight can pause "
            "in-progress ads. Inspect shopai roas first."
        ),
        "severity": "info",
    },
    "transfer scan": {
        "flags": ["history_thin_risk"],
        "rationale": (
            "Transfer-scan ranks by past outcomes. Stores "
            "with <3 attributed orders give weak signal."
        ),
        "severity": "info",
    },
    "roas": {
        "flags": ["needs_attribution_window"],
        "rationale": (
            "ROAS quality depends on accurate attribution "
            "window; verify shopai cycle attribution "
            "snapshots are fresh first."
        ),
        "severity": "info",
    },
    "engine ranking": {
        "flags": ["cold_start_bias"],
        "rationale": (
            "Engine ranking penalises cold-start engines "
            "with no outcomes yet -- the top of the list "
            "may not be the best newcomer."
        ),
        "severity": "info",
    },
}


# Verdict-level critiques: structural risks that apply
# regardless of which specific action was proposed.
_VERDICT_RISKS: dict[str, dict[str, Any]] = {
    "no_data": {
        "flags": ["empire_idle"],
        "rationale": (
            "Empire is idle; any forward action might "
            "succeed but won't validate hypotheses. "
            "Consider measuring first."
        ),
        "severity": "info",
    },
    "attributed_loss": {
        "flags": ["bleeding"],
        "rationale": (
            "Loss is accruing; act on rank-1 within "
            "operator's awareness window. Delays = cost."
        ),
        "severity": "critical",
    },
    "organic_only": {
        "flags": ["agi_not_attributed"],
        "rationale": (
            "0% attribution means orders flow but AGI "
            "didn't move them. Acting on the wrong engine "
            "won't change attribution."
        ),
        "severity": "warn",
    },
    "earning": {
        "flags": [],
        "rationale": "",
        "severity": "info",
    },
}


def _gather_proposals(store_id: str) -> tuple[
    list[dict[str, Any]], str,
]:
    """Pull proposed actions from W963-52 + the verdict."""
    try:
        from engines.llm_action_proposer.proposer import (
            propose,
        )
        report = propose(store_id=store_id)
        return (
            [
                {
                    "rank": a.rank,
                    "action": a.action,
                    "cli_command": a.cli_command,
                    "priority": a.priority,
                }
                for a in report.proposed
            ],
            report.verdict,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "action_critic: gather raised: %s", exc,
        )
        return [], "no_data"


def _deterministic_baseline(
    proposed: list[dict[str, Any]], verdict: str,
) -> list[Critique]:
    out: list[Critique] = []
    verdict_risk = _VERDICT_RISKS.get(verdict, {})
    for a in proposed:
        rank = int(a.get("rank") or 0)
        action = str(a.get("action") or "")
        cli = str(a.get("cli_command") or "")
        c = Critique(
            rank=rank, action=action, cli_command=cli,
        )
        # Substring matching against anti-patterns
        flags: list[str] = []
        rationales: list[str] = []
        severity = "info"
        for trigger, anti in _ANTI_PATTERNS.items():
            if trigger in cli:
                flags.extend(anti.get("flags") or [])
                ration = anti.get("rationale", "")
                if ration:
                    rationales.append(ration)
                sev = anti.get("severity", "info")
                if _severity_rank(sev) > _severity_rank(
                    severity,
                ):
                    severity = sev
        # Verdict-level adds
        vflags = verdict_risk.get("flags") or []
        if vflags:
            flags.extend(vflags)
        vrat = verdict_risk.get("rationale", "")
        if vrat:
            rationales.append(vrat)
        vsev = verdict_risk.get("severity", "info")
        if _severity_rank(vsev) > _severity_rank(severity):
            severity = vsev
        # De-dupe flags preserving order
        seen: set[str] = set()
        dedup: list[str] = []
        for f in flags:
            if f not in seen:
                seen.add(f)
                dedup.append(f)
        c.risk_flags = dedup
        c.counter_rationale = " ".join(rationales)
        c.severity = severity
        out.append(c)
    return out


def _severity_rank(s: str) -> int:
    return {
        "info": 0, "warn": 1, "critical": 2,
    }.get(s, 0)


def _build_prompt(
    critiques: list[Critique], verdict: str, store_id: str,
) -> tuple[str, str]:
    system = (
        "You are an adversarial reviewer of an autonomous "
        "e-commerce empire's next-action plan. You will be "
        "given the empire verdict and 3 proposed actions "
        "with their baseline risk_flags + counter_rationale. "
        "Refine the counter_rationale strings only -- one "
        "sentence each, sharpening the most plausible "
        "failure mode. Do NOT remove or invent risk_flags. "
        "Do NOT change action labels, CLI commands, or "
        "severities. Return JSON {\"counters\": "
        "[{\"rank\": int, \"counter_rationale\": str}]}."
    )
    lines = [
        f"Store: {store_id or '(fleet)'}",
        f"Verdict: {verdict}",
        "Proposed actions + baseline critique:",
    ]
    for c in critiques:
        lines.append(
            f"  #{c.rank} [{c.severity}] {c.action} -> "
            f"{c.cli_command}"
        )
        lines.append(
            f"     flags: {', '.join(c.risk_flags) or '(none)'}"
        )
        lines.append(
            f"     baseline counter: {c.counter_rationale}"
        )
    return system, "\n".join(lines)


def _refine_with_llm(
    critiques: list[Critique], verdict: str, store_id: str,
) -> tuple[list[Critique], bool, str]:
    if not _ai_enabled():
        return critiques, False, "SHOPAI_AI_STRATEGY not set"
    if _is_test_environment():
        return critiques, False, "pytest guard"
    try:
        from engines._ai_strategies import _LLMClient
    except Exception as exc:  # noqa: BLE001
        return critiques, False, f"client import: {exc}"
    client = _LLMClient()
    if not client.available:
        return critiques, False, "no LLM client available"
    if not critiques:
        return critiques, False, "no critiques to refine"
    system, user = _build_prompt(
        critiques, verdict, store_id,
    )
    try:
        parsed = client.chat_json(system, user)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "action_critic: chat raised: %s", exc,
        )
        return critiques, False, f"chat raised: {exc}"
    if not isinstance(parsed, dict):
        return critiques, False, "non-dict response"
    counters = parsed.get("counters")
    if not isinstance(counters, list):
        return critiques, False, "missing counters list"
    by_rank: dict[int, str] = {}
    for item in counters:
        if not isinstance(item, dict):
            continue
        try:
            r = int(item.get("rank"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("counter_rationale") or "")
        if r and text:
            by_rank[r] = text[:300]
    for c in critiques:
        if c.rank in by_rank:
            c.counter_rationale = by_rank[c.rank]
    return critiques, True, "ok"


def critique(
    *,
    store_id: str = "",
    proposed_override: list[dict[str, Any]] | None = None,
    verdict_override: str = "",
) -> CritiqueReport:
    if proposed_override is not None:
        proposed = proposed_override
        verdict = verdict_override or "no_data"
    else:
        proposed, verdict = _gather_proposals(store_id)
    report = CritiqueReport(
        store_id=store_id, verdict=verdict,
    )
    crits = _deterministic_baseline(proposed, verdict)
    crits, used, reason = _refine_with_llm(
        crits, verdict, store_id,
    )
    report.critiques = crits
    report.llm_used = used
    report.llm_reason = reason
    return report
