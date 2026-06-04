"""Compose multi-step substrate plans from goal phrases.

Two strategies:
  1. Template match: goal phrase matches a built-in canonical
     plan ("cold_start", "increase_conversion", etc.)
  2. Custom compose: goal → capability_browser → strategist
     context → ranked step list. Less precise but flexible.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    order: int
    action: str
    engine: str = ""
    drill_command: str = ""
    reasoning: str = ""
    impact: str = "medium"
    expected_outcome: str = ""


@dataclass
class Plan:
    goal: str
    store_id: str
    template_matched: str = ""  # canonical plan name or ""
    confidence: float = 0.0
    steps: list[PlanStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ── Canonical templates ─────────────────────────────────


_TEMPLATES: dict[str, dict[str, Any]] = {
    "cold_start": {
        "aliases": [
            "cold start", "launch store", "first sale",
            "start earning", "new store",
        ],
        "confidence": 0.9,
        "steps": [
            {
                "action": "Seed product catalog",
                "engine": "earn_bootstrap",
                "drill": (
                    "shopai earn-bootstrap --niche "
                    "{niche} --count 20 --yes"
                ),
                "reasoning": (
                    "Empty stores can't earn. Catalog seed "
                    "is the precondition for every other step."
                ),
                "impact": "high",
                "expected": "20 DRAFT products in Shopify",
            },
            {
                "action": "Configure store + launch policies",
                "engine": "launch_orchestrator",
                "drill": (
                    "shopai store configure {store_id} && "
                    "shopai launch \"Store\" --niche {niche}"
                ),
                "reasoning": (
                    "Without legal pages + checkout setup "
                    "the store can't transact."
                ),
                "impact": "high",
                "expected": "9/11 launch-audit gates pass",
            },
            {
                "action": "Seed SEO blog content",
                "engine": "content_publisher",
                "drill": (
                    "shopai blog-candidates --niche {niche} "
                    "--apply"
                ),
                "reasoning": (
                    "SEO compounds over 30+ days. Start now."
                ),
                "impact": "medium",
                "expected": "10 DRAFT blog articles queued",
            },
            {
                "action": "Wire paid traffic channel",
                "engine": "ads_launcher",
                "drill": (
                    "shopai ads connect meta --token X "
                    "--account-id Y"
                ),
                "reasoning": (
                    "Organic alone rarely crosses cold_start. "
                    "Paid is the fastest revenue cycle-back."
                ),
                "impact": "high",
                "expected": "Meta Ads adapter wired",
            },
            {
                "action": "Schedule recurring cycle",
                "engine": "cycle_scheduler",
                "drill": "shopai cycle schedule",
                "reasoning": (
                    "Autonomous loop fires periodically; "
                    "operator only reviews exceptions."
                ),
                "impact": "high",
                "expected": "Cron + notify-check installed",
            },
        ],
    },
    "increase_conversion": {
        "aliases": [
            "convert better", "conversion", "improve cro",
            "boost conversion", "checkout",
        ],
        "confidence": 0.85,
        "steps": [
            {
                "action": "Diagnose funnel drop-off",
                "engine": "conversion_funnel",
                "drill": "shopai funnel --days 7",
                "reasoning": (
                    "Identify the weakest funnel link before "
                    "throwing engines at it."
                ),
                "impact": "high",
                "expected": "Verdict + weakest_link surfaced",
            },
            {
                "action": "Run CRO variant generator",
                "engine": "cro_variants",
                "drill": (
                    "shopai cro variants --niche {niche}"
                ),
                "reasoning": (
                    "If product→checkout drop is high, the "
                    "product page is the bottleneck."
                ),
                "impact": "high",
                "expected": (
                    "A/B variants generated for top product"
                ),
            },
            {
                "action": "Fire cart_recovery",
                "engine": "cart_recovery",
                "drill": (
                    "shopai approvals approve-all "
                    "--engine cart_recovery --execute"
                ),
                "reasoning": (
                    "Recover the 60-80% of carts that bail at "
                    "the checkout step."
                ),
                "impact": "high",
                "expected": (
                    "Recovery emails / codes dispatched"
                ),
            },
            {
                "action": "Wire review_request",
                "engine": "review_request",
                "drill": (
                    "shopai reviews send-batch --yes"
                ),
                "reasoning": (
                    "4.5-star average lifts conversion 15-30%."
                ),
                "impact": "medium",
                "expected": "Post-purchase asks dispatched",
            },
        ],
    },
    "increase_traffic": {
        "aliases": [
            "get traffic", "more traffic", "traffic",
            "visitors", "drive traffic",
        ],
        "confidence": 0.85,
        "steps": [
            {
                "action": "Wire paid traffic channel",
                "engine": "ads_launcher",
                "drill": (
                    "shopai ads connect meta --token X "
                    "--account-id Y"
                ),
                "reasoning": (
                    "Fastest cold-traffic source."
                ),
                "impact": "high",
                "expected": "Meta Ads adapter wired",
            },
            {
                "action": "Launch first paid campaign",
                "engine": "ads_launcher",
                "drill": (
                    "shopai ads launch --platform meta "
                    "--budget-daily 10"
                ),
                "reasoning": (
                    "PAUSED at creation by safety -- operator "
                    "activates after review."
                ),
                "impact": "high",
                "expected": "PAUSED campaign in Meta Manager",
            },
            {
                "action": "Pinterest pulse",
                "engine": "pinterest_publisher",
                "drill": (
                    "shopai pinterest publish-pin --image-url "
                    "U --title T --board-id B"
                ),
                "reasoning": (
                    "Pinterest pins generate sustained "
                    "discovery for visual niches."
                ),
                "impact": "medium",
                "expected": "1+ pin live",
            },
            {
                "action": "Instagram + TikTok",
                "engine": "instagram_publisher",
                "drill": (
                    "shopai instagram publish-post --caption "
                    "C --media-url U"
                ),
                "reasoning": (
                    "Daily social cadence compounds organic "
                    "reach over 30+ days."
                ),
                "impact": "medium",
                "expected": "Daily post cadence started",
            },
            {
                "action": "Seed blog for SEO",
                "engine": "content_publisher",
                "drill": (
                    "shopai blog-candidates --niche {niche} "
                    "--apply"
                ),
                "reasoning": (
                    "Long-tail SEO compounds over 30+ days."
                ),
                "impact": "medium",
                "expected": "10 blog drafts queued",
            },
        ],
    },
    "retain_customers": {
        "aliases": [
            "retention", "retain", "loyalty",
            "repeat buyers", "ltv",
        ],
        "confidence": 0.85,
        "steps": [
            {
                "action": "Welcome series for new customers",
                "engine": "welcome_series",
                "drill": (
                    "shopai welcome send-batch --yes"
                ),
                "reasoning": (
                    "Welcome emails have 4-5x the open rate "
                    "of standard campaigns."
                ),
                "impact": "high",
                "expected": "Welcome cadence on",
            },
            {
                "action": "Post-purchase review request",
                "engine": "review_request",
                "drill": "shopai reviews send-batch --yes",
                "reasoning": (
                    "Reviews drive social proof + conversion."
                ),
                "impact": "high",
                "expected": "Reviews dispatched",
            },
            {
                "action": "Loyalty program tiers",
                "engine": "loyalty",
                "drill": (
                    "shopai approvals approve-all "
                    "--engine loyalty --execute"
                ),
                "reasoning": (
                    "Loyalty discount codes drive repeat "
                    "purchase + LTV."
                ),
                "impact": "medium",
                "expected": "Loyalty codes minted",
            },
            {
                "action": "Win-back churned customers",
                "engine": "churn_prediction",
                "drill": (
                    "shopai approvals approve-all "
                    "--engine churn_prediction --execute"
                ),
                "reasoning": (
                    "Predicted churners get win-back offers."
                ),
                "impact": "medium",
                "expected": "Win-back codes dispatched",
            },
        ],
    },
    "diagnose": {
        "aliases": [
            "diagnose", "audit", "health check", "status",
            "what's happening",
        ],
        "confidence": 0.95,
        "steps": [
            {
                "action": "Substrate health check",
                "engine": "checkup",
                "drill": (
                    "shopai checkup --store {store_id}"
                ),
                "reasoning": (
                    "Verify substrate is wired before "
                    "blaming engines."
                ),
                "impact": "high",
                "expected": "18-engine verdict matrix",
            },
            {
                "action": "Strategist recommendation",
                "engine": "store_strategist",
                "drill": "shopai strategist --store {store_id}",
                "reasoning": (
                    "AI brain reads 5 observation signals + "
                    "ranks recommendations."
                ),
                "impact": "high",
                "expected": "Ranked recommendation list",
            },
            {
                "action": "Per-engine attribution",
                "engine": "earnings_by_engine",
                "drill": "shopai earnings-by-engine",
                "reasoning": (
                    "Which W963 engines actually produced "
                    "revenue this week?"
                ),
                "impact": "medium",
                "expected": "18-row attribution table",
            },
            {
                "action": "Empire bigpicture",
                "engine": "bigpicture",
                "drill": (
                    "shopai bigpicture --store {store_id}"
                ),
                "reasoning": (
                    "Single-screen synthesis: today + "
                    "earnings + warmup."
                ),
                "impact": "low",
                "expected": "One-screen overview",
            },
        ],
    },
}


def _match_template(query: str) -> str | None:
    """Find the canonical template key matching the goal."""
    q = (query or "").lower().strip()
    if not q:
        return None
    # Exact key match
    if q in _TEMPLATES:
        return q
    # Alias match
    for key, tmpl in _TEMPLATES.items():
        for alias in tmpl.get("aliases") or []:
            if alias in q or q in alias:
                return key
    # Token overlap fallback
    q_tokens = set(q.split())
    best = None
    best_score = 0
    for key, tmpl in _TEMPLATES.items():
        target = key + " " + " ".join(
            tmpl.get("aliases") or [],
        )
        target_tokens = set(target.lower().split())
        overlap = len(q_tokens & target_tokens)
        if overlap > best_score:
            best_score = overlap
            best = key
    if best_score >= 1:
        return best
    return None


def _resolve_niche(store_id: str) -> str:
    if not store_id:
        return "general"
    try:
        from data_pipeline.store.store_manager import StoreManager
        row = StoreManager().get_store(store_id) or {}
        return (
            (row.get("niche") or "").strip().lower()
            or "general"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "plan_composer: niche lookup raised: %s", exc,
        )
        return "general"


def _expand_drill(drill: str, *, niche: str, store_id: str) -> str:
    try:
        return drill.format(
            niche=niche, store_id=store_id or "main",
        )
    except (KeyError, ValueError):
        return drill


def _custom_compose(
    query: str, *, store_id: str, max_steps: int,
) -> Plan:
    """When no template matches, fall back to capability_browser
    ranking + wrap top hits as plan steps."""
    plan = Plan(goal=query, store_id=store_id, confidence=0.4)
    try:
        from engines.capability_browser.searcher import (
            search_capabilities,
        )
        report = search_capabilities(query=query, top=max_steps)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "plan_composer: custom compose raised: %s", exc,
        )
        return plan

    if not report.hits:
        plan.notes.append(
            f"No engines matched goal {query!r}. "
            "Try a canonical phrase: cold_start, "
            "increase_conversion, increase_traffic, "
            "retain_customers, diagnose."
        )
        return plan

    plan.confidence = min(0.4 + 0.1 * len(report.hits), 0.7)
    niche = _resolve_niche(store_id)
    for i, hit in enumerate(report.hits, 1):
        drill = (
            hit.cli_commands[0]
            if hit.cli_commands else ""
        )
        plan.steps.append(PlanStep(
            order=i,
            action=hit.name.replace("_", " ").title(),
            engine=hit.name,
            drill_command=(
                f"shopai {_expand_drill(drill, niche=niche, store_id=store_id)}"
                if drill else f"shopai engine pulse {hit.name}"
            ),
            reasoning=(
                hit.description
                or f"Ranked by capability_browser (score={hit.score})"
            )[:150],
            impact=(
                "high" if hit.score >= 5.0
                else "medium" if hit.score >= 2.0
                else "low"
            ),
            expected_outcome=(
                hit.when_to_use[:80] if hit.when_to_use
                else "see engine docs"
            ),
        ))
    return plan


def compose_plan(
    *,
    goal: str,
    store_id: str = "",
    max_steps: int = 10,
) -> Plan:
    """Build a Plan for the goal. Tries template match first;
    falls back to custom compose."""
    max_steps = max(1, min(max_steps, 20))
    template_key = _match_template(goal)

    if template_key:
        tmpl = _TEMPLATES[template_key]
        niche = _resolve_niche(store_id)
        plan = Plan(
            goal=goal,
            store_id=store_id,
            template_matched=template_key,
            confidence=float(tmpl.get("confidence", 0.8)),
        )
        for i, raw in enumerate(
            tmpl.get("steps") or [], 1,
        ):
            if i > max_steps:
                break
            plan.steps.append(PlanStep(
                order=i,
                action=raw.get("action", ""),
                engine=raw.get("engine", ""),
                drill_command=_expand_drill(
                    raw.get("drill", ""),
                    niche=niche,
                    store_id=store_id,
                ),
                reasoning=raw.get("reasoning", ""),
                impact=raw.get("impact", "medium"),
                expected_outcome=raw.get("expected", ""),
            ))
        return plan

    return _custom_compose(
        goal, store_id=store_id, max_steps=max_steps,
    )


def available_templates() -> list[str]:
    return sorted(_TEMPLATES.keys())
