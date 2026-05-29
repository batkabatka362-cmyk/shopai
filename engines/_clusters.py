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
})


def unassigned_domain_engines(engines_dir: str = "engines") -> list[str]:
    """Like ``unassigned_engines()`` but filters out
    orchestrator-level utilities that legitimately don't
    belong to a cluster."""
    return [
        e for e in unassigned_engines(engines_dir)
        if e not in _ORCHESTRATOR_UTILITIES
    ]
