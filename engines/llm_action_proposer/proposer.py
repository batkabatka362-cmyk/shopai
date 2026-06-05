"""Deterministic action proposer + LLM rationale refinement."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProposedAction:
    rank: int
    action: str          # short label
    cli_command: str     # exact shopai command
    rationale: str       # why this is the next move
    priority: str        # critical / normal / info


@dataclass
class ProposalReport:
    store_id: str
    verdict: str
    proposed: list[ProposedAction] = field(
        default_factory=list,
    )
    llm_used: bool = False
    llm_reason: str = ""
    signals: dict[str, Any] = field(default_factory=dict)


def _is_test_environment() -> bool:
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _ai_enabled() -> bool:
    return bool(os.environ.get("SHOPAI_AI_STRATEGY"))


def _gather_signals(store_id: str) -> dict[str, Any]:
    sig: dict[str, Any] = {
        "verdict": "no_data",
        "gross_profit": 0.0,
        "attribution_pct": 0.0,
        "trend_verdict": "no_data",
        "pending_approvals": 0,
        "store_count": 0,
    }
    try:
        from engines.agi_earnings_summary.summarizer import (
            compute_summary,
        )
        s = compute_summary(days=7)
        sig["verdict"] = s.verdict
        sig["gross_profit"] = s.fleet_gross_profit
        sig["attribution_pct"] = s.fleet_attribution_pct
        sig["trend_verdict"] = s.trend_verdict
        sig["store_count"] = s.store_count
        sig["profitable_store_count"] = (
            s.profitable_store_count
        )
        sig["loss_store_count"] = s.loss_store_count
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "action_proposer: summary raised: %s", exc,
        )
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        sig["pending_approvals"] = len(
            q.list_by_status("pending") or [],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "action_proposer: approvals raised: %s", exc,
        )
    return sig


def _deterministic_baseline(
    sig: dict[str, Any], store_id: str,
) -> list[ProposedAction]:
    """Always produces exactly 3 prioritised actions."""
    verdict = str(sig.get("verdict") or "no_data")
    pending = int(sig.get("pending_approvals") or 0)
    profit = float(sig.get("gross_profit") or 0)
    loss_n = int(sig.get("loss_store_count") or 0)
    trend = str(sig.get("trend_verdict") or "no_data")
    store_args = (
        f" --store {store_id}" if store_id else ""
    )
    acts: list[ProposedAction] = []

    if verdict == "no_data":
        acts.append(ProposedAction(
            rank=1,
            action="kick off a cycle",
            cli_command="shopai cycle run --yes",
            rationale=(
                "Empire is idle. A cycle generates "
                "decisions for engines to act on."
            ),
            priority="critical",
        ))
        acts.append(ProposedAction(
            rank=2,
            action="seed the catalog",
            cli_command=(
                "shopai earn-bootstrap" + store_args
            ),
            rationale=(
                "Without products, downstream engines "
                "(pricing, ads, content) have nothing to "
                "act on."
            ),
            priority="critical",
        ))
        acts.append(ProposedAction(
            rank=3,
            action="check go-live readiness",
            cli_command="shopai go-live",
            rationale=(
                "Surface remaining setup gaps so the "
                "first cycle isn't blocked by missing "
                "credentials or quotas."
            ),
            priority="normal",
        ))
        return acts

    if verdict == "attributed_loss":
        acts.append(ProposedAction(
            rank=1,
            action="investigate ad ROAS",
            cli_command="shopai roas",
            rationale=(
                f"Fleet attributed loss "
                f"(${profit:.0f}) means AGI is "
                "spending on traffic that's not "
                "converting. ROAS report identifies "
                "the losing channels."
            ),
            priority="critical",
        ))
        acts.append(ProposedAction(
            rank=2,
            action="tighten spend caps",
            cli_command=(
                "shopai approvals quarantine "
                "--spend-status"
            ),
            rationale=(
                "Spend caps + the auto-pause bridge "
                "stop runaway ad burn while you "
                "investigate."
            ),
            priority="critical",
        ))
        acts.append(ProposedAction(
            rank=3,
            action="check engine alerts",
            cli_command="shopai engine alerts",
            rationale=(
                "Loss patterns often correlate with one "
                "or two misbehaving engines. Alerts "
                "surface degradation."
            ),
            priority="normal",
        ))
        return acts

    if verdict == "organic_only":
        acts.append(ProposedAction(
            rank=1,
            action="rank revenue engines by signal",
            cli_command=(
                "shopai engine ranking "
                "--sort outcome_score"
            ),
            rationale=(
                f"Revenue is flowing "
                "but 0% attributed to AGI. Check which "
                "revenue engines are wired and whether "
                "they're firing."
            ),
            priority="critical",
        ))
        acts.append(ProposedAction(
            rank=2,
            action="run the strategist advisor",
            cli_command=(
                "shopai llm-strategist" + store_args
            ),
            rationale=(
                "Strategist memory shows which signals "
                "have produced outcomes -- use it to "
                "decide which engines to arm next."
            ),
            priority="normal",
        ))
        acts.append(ProposedAction(
            rank=3,
            action="review approvals digest",
            cli_command="shopai approvals digest",
            rationale=(
                f"{pending} approvals pending. Some "
                "may be revenue-driving actions "
                "waiting for sign-off."
            ),
            priority="normal" if pending > 0 else "info",
        ))
        return acts

    # earning
    # W963-91: use canonical trend classifier so the
    # critical-escalation path catches BOTH the
    # 'falling' (summarizer) + 'declining' (history)
    # vocabularies + any future ladder added without
    # changing this call site.
    from core.agi.verdict_vocabulary import is_declining
    if is_declining(trend):
        crit = "critical"
        why = (
            "Earnings declining over the window -- "
            "act before it becomes a regression."
        )
    elif loss_n > 0:
        crit = "normal"
        why = (
            f"{loss_n} store(s) in loss while the fleet "
            "earns -- per-store drill-down warranted."
        )
    else:
        crit = "info"
        why = "Earning + trend healthy. Reinvest into growth."
    acts.append(ProposedAction(
        rank=1,
        action="review fleet earnings detail",
        cli_command=(
            f"shopai earnings-summary{store_args}"
        ),
        rationale=why,
        priority=crit,
    ))
    acts.append(ProposedAction(
        rank=2,
        action="batch-approve consensus actions",
        cli_command=(
            "shopai approvals batch-review "
            "--auto-approve-ok"
        ),
        rationale=(
            f"{pending} approvals pending; auto-approve "
            "consensus reduces operator load while "
            "earnings are healthy."
        ),
        priority="normal" if pending > 0 else "info",
    ))
    acts.append(ProposedAction(
        rank=3,
        action="scan cross-store transfer wins",
        cli_command="shopai transfer scan",
        rationale=(
            "Wins on earning stores often transfer to "
            "less-mature ones. Scan surfaces "
            "high-confidence transfers."
        ),
        priority="info",
    ))
    return acts


def _build_prompt(
    sig: dict[str, Any],
    actions: list[ProposedAction],
    store_id: str,
) -> tuple[str, str]:
    system = (
        "You are an operator's e-commerce empire advisor. "
        "You will be given the current empire verdict and "
        "a deterministic 3-action plan. Your job is to "
        "REFINE the rationale strings (one sentence each) "
        "so they read more naturally and reference the "
        "specific verdict + signals. You may NOT change: "
        "action labels, CLI commands, priorities, or ranks. "
        "Return JSON {\"rationales\": [{\"rank\": int, "
        "\"rationale\": str}]}."
    )
    sig_lines = [
        f"verdict={sig.get('verdict')}",
        f"gross_profit=${sig.get('gross_profit', 0):.0f}",
        f"attribution_pct={sig.get('attribution_pct', 0)}%",
        f"trend={sig.get('trend_verdict')}",
        f"pending_approvals={sig.get('pending_approvals')}",
        f"store_count={sig.get('store_count')}",
    ]
    sigs = ", ".join(sig_lines)
    lines = [
        f"Store: {store_id or '(fleet)'}",
        f"Signals: {sigs}",
        "Plan:",
    ]
    for a in actions:
        lines.append(
            f"  #{a.rank} [{a.priority}] {a.action} -> "
            f"{a.cli_command}"
        )
        lines.append(
            f"     baseline rationale: {a.rationale}"
        )
    return system, "\n".join(lines)


def _refine_with_llm(
    actions: list[ProposedAction],
    sig: dict[str, Any],
    store_id: str,
) -> tuple[list[ProposedAction], bool, str]:
    if not _ai_enabled():
        return actions, False, "SHOPAI_AI_STRATEGY not set"
    if _is_test_environment():
        return actions, False, "pytest guard"
    try:
        from engines._ai_strategies import _LLMClient
    except Exception as exc:  # noqa: BLE001
        return actions, False, f"client import: {exc}"
    client = _LLMClient()
    if not client.available:
        return actions, False, "no LLM client available"
    if not actions:
        return actions, False, "no actions to refine"
    system, user = _build_prompt(sig, actions, store_id)
    try:
        parsed = client.chat_json(system, user)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "action_proposer: chat raised: %s", exc,
        )
        return actions, False, f"chat raised: {exc}"
    if not isinstance(parsed, dict):
        return actions, False, "non-dict response"
    rats = parsed.get("rationales")
    if not isinstance(rats, list):
        return actions, False, "missing rationales list"
    by_rank: dict[int, str] = {}
    for item in rats:
        if not isinstance(item, dict):
            continue
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("rationale") or "")
        if rank and text:
            by_rank[rank] = text[:300]
    for a in actions:
        if a.rank in by_rank:
            a.rationale = by_rank[a.rank]
    return actions, True, "ok"


def propose(
    *,
    store_id: str = "",
    signals_override: dict[str, Any] | None = None,
) -> ProposalReport:
    sig = (
        signals_override
        if signals_override is not None
        else _gather_signals(store_id)
    )
    report = ProposalReport(
        store_id=store_id,
        verdict=str(sig.get("verdict") or "no_data"),
        signals=sig,
    )
    actions = _deterministic_baseline(sig, store_id)
    actions, used, reason = _refine_with_llm(
        actions, sig, store_id,
    )
    report.proposed = actions
    report.llm_used = used
    report.llm_reason = reason
    return report
