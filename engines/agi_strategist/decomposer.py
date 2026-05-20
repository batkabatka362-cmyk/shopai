"""AGI Strategist — goal decomposer.

Takes a high-level merchant goal and produces a structured
plan: substrategies (named sub-goals with target metrics +
recommended engines) plus first-step actions per substrategy.

Two paths (same pattern as the content-generation LLM PRs
#422-#426):

  1. **LLM path** (preferred). ``Capability.CHAT_COMPLETE``
     decomposes the goal into 3-6 substrategies with concrete
     engine recommendations drawn from ShopAI's catalogue.
  2. **Template path** (fallback). A deterministic rule-based
     decomposer that maps common goal keywords (revenue,
     retention, traffic, AOV, conversion) to canned
     substrategy sets. Used when no LLM is wired, when the
     call fails, or under pytest (Pattern J guard).

The output is consumed by ``engines.orchestration`` (which
turns plans into dependency graphs + parallel execution) and
by ``shopai goal apply <plan_id>`` (which materialises the
strategy into pending_actions on the approval queue).

Pattern Q: this module is exposed via the ``run()`` method on
``AGIStrategistEngine`` in ``flow.py``; this file's public
``decompose_goal()`` is the friendly function-style entry
that flow.py wraps in the canonical envelope.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.agi_strategist.decomposer")


# Catalogue of engines the strategist can recommend. Each
# entry: (engine_name, what_it_does, target_metric_levers).
# Kept here rather than inferred so the LLM can be steered
# toward concrete, real engine names instead of inventing
# generic "marketing" or "pricing" buckets.
_ENGINE_CATALOGUE: list[dict[str, Any]] = [
    {
        "engine": "dynamic_pricing",
        "purpose": "adjust product prices to balance margin + conversion",
        "levers": ["revenue", "margin", "conversion"],
    },
    {
        "engine": "discount_strategy",
        "purpose": "mint storewide promo codes / sales",
        "levers": ["revenue", "conversion", "aov"],
    },
    {
        "engine": "cart_recovery",
        "purpose": "discount-mint to recover abandoned carts",
        "levers": ["conversion", "revenue"],
    },
    {
        "engine": "browse_recovery",
        "purpose": "discount-mint for repeat-visit no-purchase users",
        "levers": ["conversion", "revenue"],
    },
    {
        "engine": "email_marketing",
        "purpose": "automated email campaigns + subject lines",
        "levers": ["traffic", "retention", "conversion"],
    },
    {
        "engine": "loyalty",
        "purpose": "tier-based discount codes for repeat customers",
        "levers": ["retention", "ltv"],
    },
    {
        "engine": "bundle",
        "purpose": "create cross-sell product bundles",
        "levers": ["aov", "revenue"],
    },
    {
        "engine": "upsell",
        "purpose": "post-purchase upsell offers",
        "levers": ["aov", "ltv"],
    },
    {
        "engine": "content_generation",
        "purpose": "LLM-generated product copy + ad / social content",
        "levers": ["conversion", "traffic"],
    },
    {
        "engine": "landing_page",
        "purpose": "campaign-specific landing page bodies",
        "levers": ["conversion", "traffic"],
    },
    {
        "engine": "search_optimization",
        "purpose": "per-product SEO meta for organic traffic",
        "levers": ["traffic"],
    },
    {
        "engine": "store_design",
        "purpose": "apply theme + design tokens to the live storefront",
        "levers": ["conversion"],
    },
    {
        "engine": "customer_segmentation",
        "purpose": "tag customers into retention / win-back / VIP cohorts",
        "levers": ["retention", "ltv"],
    },
    {
        "engine": "churn_prediction",
        "purpose": "score customers by churn risk for targeted win-back",
        "levers": ["retention"],
    },
    {
        "engine": "inventory",
        "purpose": "demand-forecast-driven reorder + stock alerts",
        "levers": ["revenue", "fulfillment"],
    },
    {
        "engine": "tag_management",
        "purpose": "auto-tag products by niche / season / collection",
        "levers": ["discoverability", "conversion"],
    },
    {
        "engine": "shipping_optimization",
        "purpose": "free-shipping thresholds + delivery promises",
        "levers": ["conversion", "aov"],
    },
    {
        "engine": "fraud_detection",
        "purpose": "score + tag risky orders to reduce chargebacks",
        "levers": ["margin"],
    },
]


_VALID_TARGET_METRICS: frozenset[str] = frozenset({
    "revenue", "traffic", "conversion", "aov", "ltv",
    "retention", "margin", "fulfillment", "discoverability",
    "churn", "cac", "roas",
})


# Recognised goal-keyword -> substrategy mapping for the
# deterministic template fallback. The LLM path generates
# nuanced multi-substrategy plans; the template path covers
# the common single-metric framings.
_GOAL_KEYWORD_MAP: dict[str, list[dict[str, Any]]] = {
    "revenue": [
        {
            "label": "Drive paid + organic traffic",
            "description": (
                "Expand top-of-funnel reach via SEO, content, "
                "and warm-audience ad campaigns."
            ),
            "target_metric": "traffic",
            "expected_lift_pct": 8.0,
            "priority": 2,
            "recommended_engines": [
                "search_optimization", "content_generation",
                "email_marketing",
            ],
        },
        {
            "label": "Lift conversion rate",
            "description": (
                "Improve product pages + checkout via copy + "
                "design + abandoned-cart recovery."
            ),
            "target_metric": "conversion",
            "expected_lift_pct": 6.0,
            "priority": 1,
            "recommended_engines": [
                "landing_page", "content_generation",
                "cart_recovery", "store_design",
            ],
        },
        {
            "label": "Raise average order value",
            "description": (
                "Bundle + upsell + free-shipping-threshold."
            ),
            "target_metric": "aov",
            "expected_lift_pct": 5.0,
            "priority": 3,
            "recommended_engines": [
                "bundle", "upsell", "shipping_optimization",
            ],
        },
    ],
    "retention": [
        {
            "label": "Identify at-risk customers",
            "description": (
                "Score the customer base by churn risk and "
                "segment for targeted win-back."
            ),
            "target_metric": "churn",
            "expected_lift_pct": 4.0,
            "priority": 1,
            "recommended_engines": [
                "churn_prediction", "customer_segmentation",
            ],
        },
        {
            "label": "Trigger win-back campaigns",
            "description": (
                "Targeted discount + email sequence per "
                "segment."
            ),
            "target_metric": "retention",
            "expected_lift_pct": 6.0,
            "priority": 2,
            "recommended_engines": [
                "email_marketing", "browse_recovery", "loyalty",
            ],
        },
        {
            "label": "Reward loyal customers",
            "description": (
                "Tier-based loyalty discounts that lift LTV "
                "without eroding margin."
            ),
            "target_metric": "ltv",
            "expected_lift_pct": 3.0,
            "priority": 3,
            "recommended_engines": ["loyalty"],
        },
    ],
    "traffic": [
        {
            "label": "Capture organic search",
            "description": (
                "Per-product SEO meta + content body so listings "
                "rank for relevant queries."
            ),
            "target_metric": "traffic",
            "expected_lift_pct": 7.0,
            "priority": 1,
            "recommended_engines": [
                "search_optimization", "content_generation",
            ],
        },
        {
            "label": "Re-engage warm audiences",
            "description": (
                "Email + browse-recovery + abandoned-cart flows "
                "drive previously-interested visitors back."
            ),
            "target_metric": "traffic",
            "expected_lift_pct": 4.0,
            "priority": 2,
            "recommended_engines": [
                "email_marketing", "browse_recovery", "cart_recovery",
            ],
        },
    ],
    "conversion": [
        {
            "label": "Polish landing + product pages",
            "description": (
                "LLM-generated landing copy + product "
                "descriptions tuned to brand voice."
            ),
            "target_metric": "conversion",
            "expected_lift_pct": 5.0,
            "priority": 1,
            "recommended_engines": [
                "landing_page", "content_generation",
                "store_design",
            ],
        },
        {
            "label": "Recover cart abandoners",
            "description": (
                "Email-discount sequence triggered by "
                "abandoned-cart webhooks."
            ),
            "target_metric": "conversion",
            "expected_lift_pct": 4.0,
            "priority": 2,
            "recommended_engines": ["cart_recovery", "email_marketing"],
        },
    ],
    "aov": [
        {
            "label": "Add cross-sell bundles",
            "description": (
                "Create bundle products + position them on "
                "high-intent pages."
            ),
            "target_metric": "aov",
            "expected_lift_pct": 6.0,
            "priority": 1,
            "recommended_engines": ["bundle", "upsell"],
        },
        {
            "label": "Free shipping threshold",
            "description": (
                "Raise the free-shipping threshold a bit above "
                "current AOV to encourage add-ons."
            ),
            "target_metric": "aov",
            "expected_lift_pct": 4.0,
            "priority": 2,
            "recommended_engines": ["shipping_optimization"],
        },
    ],
}


def decompose_goal(
    *,
    goal: str,
    horizon_days: int = 90,
    current_state: dict[str, Any] | None = None,
    constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Decompose a high-level merchant goal into substrategies.

    Args:
        goal: Free-form operator goal (e.g. "Increase revenue
            10% this quarter", "Reduce churn 2pt over 60 days").
        horizon_days: Time horizon -- biases the plan toward
            quick wins (shorter) or compounding strategies
            (longer). Default 90 (one quarter).
        current_state: Optional snapshot of current metrics
            ({monthly_revenue, aov, conversion_rate, ...}) so
            the strategist can size expected lifts realistically.
        constraints: Optional list of operator constraints
            (e.g. "no paid ads below 2.5 ROAS", "no product
            launches before Q3").

    Returns:
        Dict with the schema:
        ``{
          status: "success" | "error",
          data: {
            goal, horizon_days, substrategies: [...],
            confidence, model_note,
          },
          meta: {engine: "agi_strategist", ...},
          error: None | str,
        }``
    """
    goal_clean = (goal or "").strip()
    if not goal_clean:
        return _envelope(
            status="error",
            data={},
            error="empty_goal",
        )

    current_state = current_state or {}
    constraints = constraints or []

    # ── Path 1: LLM ──────────────────────────────────────────
    llm_plan = _decompose_via_llm(
        goal=goal_clean,
        horizon_days=horizon_days,
        current_state=current_state,
        constraints=constraints,
    )
    if llm_plan is not None:
        return _envelope(status="success", data=llm_plan)

    # ── Path 2: Template fallback ────────────────────────────
    plan = _decompose_via_template(
        goal=goal_clean,
        horizon_days=horizon_days,
    )
    return _envelope(status="success", data=plan)


def _envelope(
    *,
    status: str,
    data: dict[str, Any],
    error: str | None = None,
) -> dict[str, Any]:
    """Wrap the result in the canonical engine envelope."""
    return {
        "status": status,
        "data": data,
        "meta": {"engine": "agi_strategist"},
        "error": error,
    }


# ---------------------------------------------------------------------------
# LLM-driven decomposition
# ---------------------------------------------------------------------------


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _decompose_via_llm(
    *,
    goal: str,
    horizon_days: int,
    current_state: dict[str, Any],
    constraints: list[str],
) -> dict[str, Any] | None:
    """LLM-driven goal decomposition.

    Returns the plan dict on success, ``None`` on any failure
    (caller falls back to the template path). Never raises.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router import failed: %s", exc)
        return None

    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router init failed: %s", exc)
        return None

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        goal=goal,
        horizon_days=horizon_days,
        current_state=current_state,
        constraints=constraints,
    )

    try:
        result = router.execute(Capability.CHAT_COMPLETE, {
            "system": system_prompt,
            "prompt": user_prompt,
            "max_tokens": 2000,
            "temperature": 0.5,  # strategy favors structure over flair
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM call raised: %s", exc)
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "LLM call returned not-ok: %s",
            getattr(result, "error", "unknown"),
        )
        return None

    text = ((result.data or {}).get("text") or "").strip()
    if not text:
        return None

    parsed = _parse_llm_json(text)
    if not parsed:
        return None

    substrategies_raw = parsed.get("substrategies")
    if not isinstance(substrategies_raw, list) or not substrategies_raw:
        return None

    substrategies = _validate_substrategies(substrategies_raw)
    if not substrategies:
        return None

    confidence_raw = parsed.get("confidence", 0.7)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    model = ""
    try:
        model = str((result.data or {}).get("model") or "")
    except Exception:  # noqa: BLE001
        pass

    return {
        "goal": goal,
        "horizon_days": int(horizon_days),
        "substrategies": substrategies,
        "confidence": round(confidence, 2),
        "model_note": f"llm: {model}" if model else "llm: provider-default",
    }


def _validate_substrategies(
    raw: list[Any],
) -> list[dict[str, Any]]:
    """Defensively coerce + drop invalid LLM substrategies.

    Each substrategy must carry label + description + a
    recognised target_metric + at least one engine. Items
    failing these are dropped silently; the engine fails
    closed (returns ``None`` upstream if NO valid items
    remain) so the caller falls back to template.
    """
    catalogue_engines = {e["engine"] for e in _ENGINE_CATALOGUE}
    out: list[dict[str, Any]] = []

    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        description = str(item.get("description") or "").strip()
        if not label or not description:
            continue

        target_metric = str(item.get("target_metric") or "").strip().lower()
        if target_metric not in _VALID_TARGET_METRICS:
            continue

        engines_raw = item.get("recommended_engines") or []
        if not isinstance(engines_raw, list):
            continue
        engines = [
            str(e).strip() for e in engines_raw
            if isinstance(e, str)
            and str(e).strip() in catalogue_engines
        ]
        if not engines:
            # The LLM made up an engine name -- drop the whole
            # substrategy. We don't surface phantom engines
            # downstream because orchestration would silently
            # fail to dispatch them.
            continue

        try:
            expected_lift_pct = float(item.get("expected_lift_pct", 5.0))
        except (TypeError, ValueError):
            expected_lift_pct = 5.0
        expected_lift_pct = max(0.0, min(100.0, expected_lift_pct))

        try:
            priority = int(item.get("priority", 3))
        except (TypeError, ValueError):
            priority = 3
        priority = max(1, min(5, priority))

        out.append({
            "label": label,
            "description": description,
            "target_metric": target_metric,
            "expected_lift_pct": round(expected_lift_pct, 1),
            "priority": priority,
            "recommended_engines": engines[:5],
        })

    return out


def _build_system_prompt() -> str:
    catalogue_lines = "\n".join(
        f"  - {e['engine']} -- {e['purpose']}"
        for e in _ENGINE_CATALOGUE
    )
    metrics = ", ".join(sorted(_VALID_TARGET_METRICS))
    return (
        "You are the chief strategist for ShopAI, an "
        "autonomous AGI merchant operating a Shopify store. "
        "Given a high-level merchant goal, decompose it into "
        "3-6 concrete substrategies. Each substrategy must:\n"
        "  - target a specific named metric\n"
        "  - reference at least one engine from the catalogue "
        "below (DO NOT INVENT engine names)\n"
        "  - estimate expected lift as a percentage\n"
        "  - have a priority 1-5 (1 = run first)\n\n"
        f"Valid metrics: {metrics}.\n\n"
        f"Engine catalogue:\n{catalogue_lines}\n\n"
        "Always respond with STRICT JSON in the requested "
        "shape; no markdown fences, no commentary."
    )


def _build_user_prompt(
    *,
    goal: str,
    horizon_days: int,
    current_state: dict[str, Any],
    constraints: list[str],
) -> str:
    state_lines = "\n".join(
        f"  - {k}: {v}" for k, v in current_state.items()
    ) or "  (no current-state snapshot provided)"
    constraint_lines = "\n".join(
        f"  - {c}" for c in constraints
    ) or "  (none)"
    return (
        f"Goal: {goal}\n"
        f"Horizon: {horizon_days} days\n"
        f"Current state:\n{state_lines}\n"
        f"Constraints:\n{constraint_lines}\n\n"
        "Return STRICT JSON in this exact shape:\n"
        "{\n"
        '  "substrategies": [\n'
        "    {\n"
        '      "label": "short name (e.g. \\"Drive paid traffic\\")",\n'
        '      "description": "1-2 sentences on the play",\n'
        '      "target_metric": "one of the valid metrics",\n'
        '      "expected_lift_pct": 0.0,\n'
        '      "priority": 1,\n'
        '      "recommended_engines": ["engine_name_from_catalogue", ...]\n'
        "    }\n"
        "  ],\n"
        '  "confidence": 0.0  // your confidence in the plan, 0-1\n'
        "}"
    )


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON parse, tolerates markdown fences."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        pass
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------


_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("revenue", "sales", "income"), "revenue"),
    (("retention", "churn", "ltv", "loyal"), "retention"),
    (("traffic", "visitors", "reach", "awareness"), "traffic"),
    (("convert", "cvr", "checkout"), "conversion"),
    (("aov", "order value", "basket"), "aov"),
]


def _decompose_via_template(
    *,
    goal: str,
    horizon_days: int,
) -> dict[str, Any]:
    """Deterministic goal decomposition using keyword rules.

    Maps the goal's text to one of the canned substrategy
    sets in ``_GOAL_KEYWORD_MAP``. Defaults to "revenue" when
    no keyword matches because revenue is the universal
    e-commerce KPI.
    """
    bucket = _classify_goal(goal)
    substrategies = list(_GOAL_KEYWORD_MAP[bucket])

    return {
        "goal": goal,
        "horizon_days": int(horizon_days),
        "substrategies": substrategies,
        "confidence": 0.55,  # templates are best-guess
        "model_note": (
            f"template fallback: goal classified as '{bucket}' "
            "(no LLM provider configured or LLM call failed)"
        ),
    }


def _classify_goal(goal: str) -> str:
    """Classify the goal text into a known bucket via keyword
    matching. Default to ``revenue`` (universal e-commerce
    KPI) when no keyword fires."""
    lowered = goal.lower()
    for keywords, bucket in _KEYWORD_RULES:
        if any(kw in lowered for kw in keywords):
            return bucket
    return "revenue"
