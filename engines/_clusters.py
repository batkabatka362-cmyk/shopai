"""Engine clusters -- the missing Tier 2b layer.

Bibliid 135 engine flat baigaa boltgoi ant-colony architecture-d
queen worker-iig direct micromanage hiig boldoggvi. Engineuud
**concern-aaraa angilna** (cluster) -- captain bvr cluster-iin
huviid:

  • 4-12 member engine-tai
  • Cluster-iin huviid memoryt-tai (outcome stats)
  • Member-aas alin n fire hiig deciding hiig
  • Tier 2a supervisor-d cluster-health report hiig

Iim n single-step delegation amjuulna:

    Owner -> Orchestrator -> Supervisor -> Cluster Captain ->
        Engine -> Adapter -> Shopify

Bus tier zugeer **neg davhraa-iin** layer-tai medege.

This module is DATA + INDEX only. The actual captain logic
lives in engines/_cluster_captain.py.

Cluster topology (10 concerns covering all 135 engines):

  pricing      -- price optimization + margin analysis
  retention    -- keep existing customers buying
  acquisition  -- bring new customers in
  quality      -- product/order quality assurance
  merchandising -- catalog presentation + ranking
  fulfillment  -- inventory + shipping + returns
  content      -- product copy + brand voice
  governance   -- security + audits + risk monitoring
  discovery    -- market/trend/competitor research
  setup        -- store launch + design + legal

Engines not in any cluster are flagged as "unassigned" --
operators should either add them to a cluster or document
why they're standalone (orchestrator-level utilities).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Cluster:
    """A concern-grouped set of engines + a captain mandate."""
    name: str
    description: str
    members: frozenset[str]
    # Goal contribution: which root KPI this cluster ladders to.
    # Bvgd cluster "Autonomous Profitable Operation"-d daraa
    # ladder hiine. Specific KPI cluster-aaraa:
    kpi: str

    def has_member(self, engine_name: str) -> bool:
        return engine_name in self.members


# ── Cluster definitions ────────────────────────────────────────
#
# Yag odoogiin engine-uudiig 10 concern-d angiluulsan. Anhanii
# draft -- captain logic-iig daraah commit-d bvtegne. Engine
# nemegduunged ene mapping-iig sajruulna.

_CLUSTERS: tuple[Cluster, ...] = (
    Cluster(
        name="pricing",
        description=(
            "Price optimization, elasticity analysis, margin "
            "management. Decides what each product should cost "
            "+ surfaces margin-risk products."
        ),
        members=frozenset({
            "pricing",
            "dynamic_pricing",
            "price_elasticity",
            "profitability_calculator",
            "profit_optimization",
            "dropshipping",  # margin from supplier cost
            "discount_strategy",
        }),
        kpi="margin_pct + revenue",
    ),
    Cluster(
        name="retention",
        description=(
            "Keep existing customers buying. Churn prediction, "
            "loyalty programs, subscription health, cohort "
            "tracking, journey staging."
        ),
        members=frozenset({
            "loyalty",
            "churn_prediction",
            "subscription",
            "cohort_analysis",
            "customer_journey",
            "browse_recovery",
            "cart_recovery",
            "nps_engine",
            "customer_effort_score",
            # Phase 15 + 27 autonomy: post-purchase nurture
            # and at-risk customer tagging
            "order_followup_autonomy",
            "customer_outreach_autonomy",
        }),
        kpi="repeat_rate + ltv",
    ),
    Cluster(
        name="acquisition",
        description=(
            "Bring new customers in. Targeting, ads, email "
            "lifecycle, affiliate, influencer programs."
        ),
        members=frozenset({
            "audience_targeting",
            "email_marketing",
            "affiliate",
            "influencer",
            "customer_segmentation",
            "ad_creative_generator",
            "campaign_strategy",
            "conversion_tracking",
            "wholesale_b2b",          # B2B segment acquisition
        }),
        kpi="new_customer_count + cac",
    ),
    Cluster(
        name="quality",
        description=(
            "Product + order + customer-experience quality "
            "assurance. Catches issues BEFORE they hit "
            "revenue."
        ),
        members=frozenset({
            "warranty",
            "order_quality",
            "fraud_detection",
            "review_management",
            "customer_service",
            "customer_support",
            "feedback_collection",
            "feedback_processing",
            "sentiment_analysis",
            "product_risk",
            "product_validation",
        }),
        kpi="defect_rate + sentiment_score (inverted)",
    ),
    Cluster(
        name="merchandising",
        description=(
            "Catalog presentation. Which products feature, "
            "which to rank highest, which to surface for "
            "browse + behavioral data. Also catalog lifecycle "
            "(archive declining, optimize variants)."
        ),
        members=frozenset({
            "product_ranking",
            "product_scoring",
            "behavioral_data",
            "wishlist",
            "cross_sell",
            "upsell",
            "bundle",
            "catalog",
            "tag_management",
            "search_optimization",
            "selection_decision",
            "product_filter",
            "product_lifecycle",
            "product_optimization",
            # Phase 18 + 28 autonomy: SEO + quality catalog
            # presentation
            "product_seo_autonomy",
            "catalog_quality_autonomy",
        }),
        kpi="conversion_rate + AOV",
    ),
    Cluster(
        name="fulfillment",
        description=(
            "Inventory health, shipping, returns. Operations "
            "side of selling -- products in stock, orders "
            "delivered, returns handled."
        ),
        members=frozenset({
            "inventory",
            "stock_prediction",
            "returns_management",
            "shipping_optimization",
            "order_management",
            "supplier",
            "supplier_communication",
            "supplier_discovery",
            # Phase 11-28 autonomy domains in fulfillment
            "fulfillment_autonomy",
            "inventory_autonomy",
            # Phase 35: shipping alert tagging
            "shipping_alert_autonomy",
        }),
        kpi="fulfillment_time + stockout_rate (inverted)",
    ),
    Cluster(
        name="content",
        description=(
            "Product copy, brand voice, descriptions, images. "
            "Operator-managed because content generation is "
            "user's domain -- cluster surfaces recommendations "
            "but doesn't auto-write."
        ),
        members=frozenset({
            "product_description",
            "content_generation",
            "brand_identity",
            "brand_voice_enforcer",
            "brand_visual",
            "brand_positioning",
            "brand_perception",
            "image_optimization",
            "video_marketing",
            "social_media",
            "landing_page",
        }),
        kpi="creative_engagement + brand_consistency",
    ),
    Cluster(
        name="governance",
        description=(
            "Security, monitoring, risk audits. The defense "
            "layer -- catches things going wrong + enforces "
            "policy boundaries."
        ),
        members=frozenset({
            "security_monitor",
            "performance_monitor",
            "kpi_tracking",
            "report_dashboard",
            "tax_engine",
            "accounting",
            "legal_document",
            # Phase 14 autonomy: discount cleanup is a
            # governance / housekeeping concern
            "discount_cleanup_autonomy",
            "compliance" if False else "",  # placeholder
        }) - frozenset({""}),
        kpi="incident_count (inverted) + audit_pass_rate",
    ),
    Cluster(
        name="discovery",
        description=(
            "Market intelligence + competitor + trend "
            "research. Mostly read-only -- finds opportunities "
            "for other clusters to act on."
        ),
        members=frozenset({
            "auto_research",
            "market_research",
            "trend_detection",
            "trend_discovery",
            "winning_products",
            "product_selection",
            "product_research",
            "opportunity_detection",
            "opportunity_scoring",
            "demand_analysis",
            "demand_estimator",
            "competitor_analysis",
            "competitor_monitor",
            "competitor_ad_intelligence",
            "competition_analyzer",
            "competitor_social",
            "competitor_reaction_simulator",
            "customer_behavior_simulator",
            "market_simulator",
            "simulation_lab",
        }),
        kpi="signals_actioned_count",
    ),
    Cluster(
        name="setup",
        description=(
            "Store launch + configuration. Mostly run-once "
            "during store onboarding. Doesn't fire during "
            "normal autonomous-cycle."
        ),
        members=frozenset({
            "store_design",
            "store_setup",
            "product_launch",
            "product_variant",
        }),
        kpi="launch_readiness_score",
    ),
)


def list_clusters() -> tuple[Cluster, ...]:
    """All registered clusters in stable order."""
    return _CLUSTERS


def get_cluster(name: str) -> Cluster | None:
    """Lookup a cluster by name. Returns None if not found."""
    for c in _CLUSTERS:
        if c.name == name:
            return c
    return None


def cluster_for_engine(engine_name: str) -> Cluster | None:
    """Find which cluster an engine belongs to (None if unassigned)."""
    for c in _CLUSTERS:
        if c.has_member(engine_name):
            return c
    return None


def unassigned_engines(engines_dir: str = "engines") -> list[str]:
    """Return engine names not assigned to any cluster.

    Walked from the engines/ directory. Useful as a CI invariant:
    every engine SHOULD be in a cluster -- unassigned engines are
    either orchestrator-level utilities (and should be excluded
    from this audit) or were forgotten when their cluster was
    defined.
    """
    root = Path(engines_dir)
    if not root.exists():
        return []
    out: list[str] = []
    all_members: set[str] = set()
    for c in _CLUSTERS:
        all_members |= c.members
    for engine_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        name = engine_dir.name
        if name.startswith("_") or name == "base":
            continue
        # Must contain at least a flow.py to count as an engine
        if not (engine_dir / "flow.py").exists():
            # winning_products is run() style, accept it too
            if not any(engine_dir.glob("*.py")):
                continue
        if name not in all_members:
            out.append(name)
    return out


# Engines KNOWN to be orchestrator-level utilities, not domain
# engines. They legitimately don't belong to a cluster.
_ORCHESTRATOR_UTILITIES = frozenset({
    "agi_strategist",        # AI strategist, not a worker
    "autonomous_control",    # Tier 1 controller
    "autonomous_decision",   # Tier 1 decision
    "autonomous_execution",  # Tier 1 executor
    "global_brain",          # Tier 1 brain
    "meta_governance",       # Tier 1 governance
    "orchestration",         # Tier 1 orchestrator
    "execution_intelligence",# Tier 1 execution layer
    "learning_loop",         # Cross-cutting memory
    "backup_recovery",       # Tier 0 infra
    "data_collection",       # Tier 0 infra
    "data_enrichment",       # Tier 0 infra
    "event_tracking",        # Tier 0 infra
    "webhook_handler",       # Tier 0 infra
    "workflow_builder",      # Tier 0 infra
    "notification",          # Tier 0 infra
    "chatbot",               # Tier 0 surface
    "email_reporter",        # Tier 0 surface
    "sop_generator",         # Tier 0 surface
    "team_task_manager",     # Tier 0 surface
    "time_intelligence",     # Tier 0 infra
    "checkout_optimizer",    # Tier 4 (Shopify-built-in surface)
    "infinite_scaling",      # Strategic meta
    "ltv_cac_dashboard",     # Dashboard surface, not engine
    "monetization",          # Strategic meta
    "marketplace",           # Multi-platform meta
    "international_expansion", # Strategic meta
    "forecasting",           # Cross-cluster utility
    "cashflow_simulator",    # Financial simulator
    "cash_flow",             # Financial utility
    "financial",             # Financial utility
    "payment_optimization",  # Cross-cluster payment
    "ab_testing",            # Cross-cluster experiment framework
    "selection_reasoning",   # Cross-cluster explainer
    "user_tracking",         # Cross-cluster tracking
    "gift_card",             # Cross-cluster promo (could move into acquisition)
    "roas_guardrails",       # Cross-cluster ad guardrail
    "selection_decision",    # Already in merchandising (alias)
    "revenue_readiness",     # W963-1: cross-cutting diagnostic
    "product_sourcer",       # W963-2: cold-start seed generator
    "earnings_report",       # W963-4: output-side measurement
    "earn_bootstrap",        # W963-5: one-command cold-start chain
    "content_publisher",     # W963-6: SEO blog content seed
    "ads_launcher",          # W963-7: ad-platform credential + launch wrapper
    "email_connect",         # W963-8: ESP credential + send-test wrapper
    "affiliate_links",       # W963-9: per-partner referral link generator
    "pinterest_publisher",   # W963-10: Pinterest connect + publish-pin wrapper
    "cro_variants",          # W963-11: CRO title/description/price variant generator
    "tiktok_publisher",      # W963-12: TikTok connect + publish-post wrapper
    "customer_chat",         # W963-13: customer message intent + draft response
    "cold_start_orchestrator", # W963-14: end-to-end day-1 cold-start chain orchestrator
    "instagram_publisher",   # W963-15: Instagram Graph API connect + publish-post
    "review_request",        # W963-16: post-purchase review request automation
    "warmup_plan",           # W963-17: 30-day cold-start playbook generator
    "today_brief",           # W963-18: morning operator companion across 5 signals
    "earnings_by_engine",    # W963-19: per-W963-engine attribution rollup
    "bigpicture",            # W963-20: unified morning view (today + earnings + warmup)
    "checkup",               # W963-21: parallel health probe across W963 roster
    "welcome_series",        # W963-22: 3-email welcome cadence for new customers
    "autopilot",             # W963-23: end-to-end autonomous loop (welcome+review+measure+health)
    "daily_trajectory",      # W963-24: per-day revenue slope ("are we trending up?")
    "conversion_funnel",     # W963-25: per-stage drop-off (sessions/cart/checkout/paid)
    "fleet_autopilot",       # W963-26: iterate autopilot across full fleet (north-star empire mode)
    "fleet_transfer_auto",   # W963-27: auto-propagate cross-store winners as PENDING approvals
    "store_strategist",      # W963-28: per-store AGI brain - read signals, output ranked recommendations
    "confidence_auto_approver", # W963-29: track-record-based auto-approve trust-wedge widener
    "capability_browser",    # W963-30: substrate registry browser - goal -> ranked engines
    "plan_composer",         # W963-31: goal -> multi-step substrate plan (template + custom compose)
    "fleet_emergency_pause", # W963-32: single-command kill switch halting fleet-wide autonomy
    "cross_store_anomaly_detector", # W963-33: per-store metric divergence vs fleet norm (median+MAD)
    "fleet_chaos_test",      # W963-34: lightweight chaos test verifying graceful degrade (Q4)
    "fleet_strategist",      # W963-35: fleet-wide AGI brain - ranks stores by urgency x potential
    "plan_executor",         # W963-36: enqueue composed plan as PENDING approval batch
    "strategist_executor_bridge", # W963-37: strategist recs -> plan_executor (fleet autonomy bridge)
    "anomaly_auto_quarantine", # W963-38: outlier alert -> auto-pause store writers
    "confidence_calibrator", # W963-39: per-engine trust threshold based on outcome history
    "fleet_intervention_alerts", # W963-40: aggregate critical fleet signals into one operator surface
    "fleet_brief_digest",    # W963-41: morning empire synthesizer (PHASE 2 CAPSTONE)
    "fleet_notifier",        # W963-42: push critical empire events to webhook (async loop)
    "strategist_memory",     # W963-43: persistent recommendation+outcome history (Q3 substrate)
    "outcome_backfill",      # W963-44: match Shopify orders to actions, write outcomes (Phase 3.A)
    "store_pnl_tracker",     # W963-45: per-store P&L (revenue - ad spend - ESP - shipping)
    "daily_pnl_history",     # W963-46: persistent daily P&L snapshots + trend computation
    "revenue_reconciliation", # W963-47: classify revenue as AGI-attributed/organic + orphan claims
    "agi_earnings_summary",  # W963-48: composes recon + pnl + trend into single verdict
    "agi_earnings_history",  # W963-50: persistent daily verdict log + trend
    "llm_strategist_advisor",# W963-51: deterministic + LLM-refined strategist patterns
    "llm_action_proposer",   # W963-52: state-aware 3-action proposer + LLM rationale
    "llm_action_critic",     # W963-53: adversarial critique of proposer output
    "agi_morning_brief",     # W963-54: composes all Phase 3 substrate into one digest
    "agi_evening_brief",     # W963-55: day-end "what happened today?" complement
    "agi_week_review",       # W963-56: 7-day macro aggregator with verdict timeline
    "agi_anomaly_detector",  # W963-57: MAD-based sudden anomaly detector
    "cron_recommender",      # W963-59: tunes cron interval to observed signal velocity
    "agi_brief_diff",        # W963-68: day-over-day Phase 4 verdict diff
    "agi_recommend_streak",  # W963-70: consecutive un-acted recommendation streaks
    "agi_orphan_investigator", # W963-78: drill into orphan AGI attribution claims
    "agi_arm_recommender",   # W963-80: Phase 5 -- arm/disarm recommender (verdict->engines)
    "earn_config",           # W963-87: env-var setup wizard
    "earn_path",             # W963-88: smart on-ramp / "what's next?" guide
    "api_inventory",         # W963-98: ROLE-grouped credential view (operator query)
    "earn_readiness",        # W963-108: pre-launch composer (5-probe aggregate)
    "api_test",              # W963-112: live health check per configured adapter
    "per_store_costs",       # W963-118: per-store cost attribution + query
    "per_store_quota",       # W963-119: per-store budget caps + alerts
})


def unassigned_domain_engines(engines_dir: str = "engines") -> list[str]:
    """Like ``unassigned_engines()`` but filters out
    orchestrator-level utilities that legitimately don't
    belong to a cluster."""
    return [
        e for e in unassigned_engines(engines_dir)
        if e not in _ORCHESTRATOR_UTILITIES
    ]
