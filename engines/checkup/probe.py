"""Per-engine health probes for the checkup chain.

Each probe returns a HealthRow with verdict in
{ready, partial, missing, error}. Probes are best-effort: an
import failure surfaces as missing rather than crashing the
whole checkup.

The verdicts are chosen for operator-facing clarity:
  - ready    : substrate fully wired + functioning
  - partial  : substrate exists but missing 1+ dependency
               (e.g. ESP key not set, store not configured)
  - missing  : substrate not installed / import failed
  - error    : substrate raised an unexpected exception
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class HealthRow:
    engine: str
    verdict: str  # ready / partial / missing / error
    detail: str = ""
    drill: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _safe_probe(
    engine_name: str,
    fn: Callable[[], HealthRow],
) -> HealthRow:
    """Wrap a probe call so exceptions become 'error' rows."""
    try:
        return fn()
    except ImportError as exc:
        return HealthRow(
            engine=engine_name,
            verdict="missing",
            detail=f"import failed: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s probe raised: %s", engine_name, exc)
        return HealthRow(
            engine=engine_name,
            verdict="error",
            detail=f"{type(exc).__name__}: {str(exc)[:80]}",
        )


# ── Probe definitions ─────────────────────────────────────


def _probe_revenue_readiness(store_id) -> HealthRow:
    from engines.revenue_readiness import (
        RevenueReadinessEngine,
    )
    payload = {"data": {}}
    if store_id:
        payload["data"]["store_id"] = store_id
    result = RevenueReadinessEngine().run(payload)
    ok = result.get("status") == "success"
    data = result.get("data") or {}
    return HealthRow(
        engine="revenue_readiness",
        verdict="ready" if ok else "error",
        detail=f"verdict={data.get('verdict')}",
        drill="shopai diagnose",
    )


def _probe_product_sourcer() -> HealthRow:
    from engines.product_sourcer import (
        ProductSourcerEngine,
    )
    result = ProductSourcerEngine().run({
        "data": {"niche": "beauty", "count": 1},
    })
    ok = result.get("status") == "success"
    return HealthRow(
        engine="product_sourcer",
        verdict="ready" if ok else "error",
        drill="shopai product-candidates --niche X",
    )


def _probe_earn_bootstrap() -> HealthRow:
    from engines.earn_bootstrap import (
        EarnBootstrapEngine,
    )
    # Just import-and-instantiate; running fires real Shopify
    # mutations.
    EarnBootstrapEngine()
    return HealthRow(
        engine="earn_bootstrap",
        verdict="ready",
        drill="shopai earn-bootstrap --niche X --yes",
    )


def _probe_earnings_report(store_id) -> HealthRow:
    from engines.earnings_report import EarningsReportEngine
    payload = {"data": {}}
    if store_id:
        payload["data"]["store_id"] = store_id
    result = EarningsReportEngine().run(payload)
    ok = result.get("status") == "success"
    return HealthRow(
        engine="earnings_report",
        verdict="ready" if ok else "error",
        drill="shopai earnings",
    )


def _probe_content_publisher() -> HealthRow:
    from engines.content_publisher import (
        ContentPublisherEngine,
    )
    result = ContentPublisherEngine().run({
        "data": {"niche": "beauty"},
    })
    ok = result.get("status") == "success"
    return HealthRow(
        engine="content_publisher",
        verdict="ready" if ok else "error",
        drill="shopai blog-candidates --niche X",
    )


def _probe_ads_launcher() -> HealthRow:
    from engines.ads_launcher import AdsLauncherEngine
    result = AdsLauncherEngine().run({
        "data": {"action": "status"},
    })
    data = result.get("data") or {}
    # Status returns 'wired' / 'unwired' / etc.
    status = data.get("status_summary") or {}
    if any(
        v.get("wired") for v in (status.values() if isinstance(status, dict) else [])
    ):
        verdict = "ready"
    else:
        verdict = "partial"
    return HealthRow(
        engine="ads_launcher",
        verdict=verdict,
        detail=("at least one platform wired"
                if verdict == "ready"
                else "no ad platform credentials"),
        drill="shopai ads connect meta --token X",
    )


def _probe_email_connect() -> HealthRow:
    from engines.email_connect import EmailConnectEngine
    result = EmailConnectEngine().run({
        "data": {"action": "status"},
    })
    data = result.get("data") or {}
    esp_ready = data.get("esp_ready", False)
    return HealthRow(
        engine="email_connect",
        verdict="ready" if esp_ready else "partial",
        detail=("ESP wired"
                if esp_ready
                else "no ESP credentials"),
        drill="shopai email connect brevo --api-key K",
    )


def _probe_affiliate_links() -> HealthRow:
    from engines.affiliate_links import AffiliateLinksEngine
    AffiliateLinksEngine()
    return HealthRow(
        engine="affiliate_links",
        verdict="ready",
        drill="shopai affiliate generate-link --partner-email X",
    )


def _probe_social_platform(name: str) -> HealthRow:
    """Generic check for pinterest/tiktok/instagram."""
    import os
    map_env = {
        "pinterest_publisher": "PINTEREST_ACCESS_TOKEN",
        "tiktok_publisher": "TIKTOK_ACCESS_TOKEN",
        "instagram_publisher": "INSTAGRAM_ACCESS_TOKEN",
    }
    env = map_env.get(name)
    cli_map = {
        "pinterest_publisher": "shopai pinterest connect ...",
        "tiktok_publisher": "shopai tiktok connect ...",
        "instagram_publisher": "shopai instagram connect ...",
    }
    has_creds = bool(env and os.environ.get(env))
    return HealthRow(
        engine=name,
        verdict="ready" if has_creds else "partial",
        detail=("creds present"
                if has_creds
                else "no credentials"),
        drill=cli_map.get(name, ""),
    )


def _probe_cro_variants() -> HealthRow:
    # Just import-and-instantiate; running requires a real
    # product id which we don't have here.
    from engines.cro_variants import CroVariantsEngine
    CroVariantsEngine()
    return HealthRow(
        engine="cro_variants",
        verdict="ready",
        drill="shopai cro variants --product-id PID",
    )


def _probe_customer_chat() -> HealthRow:
    from engines.customer_chat import CustomerChatEngine
    result = CustomerChatEngine().run({
        "data": {"message": "Hello"},
    })
    ok = result.get("status") == "success"
    return HealthRow(
        engine="customer_chat",
        verdict="ready" if ok else "error",
        drill="shopai chat respond --message-file X",
    )


def _probe_cold_start_orchestrator() -> HealthRow:
    from engines.cold_start_orchestrator import (
        ColdStartOrchestratorEngine,
    )
    ColdStartOrchestratorEngine()
    return HealthRow(
        engine="cold_start_orchestrator",
        verdict="ready",
        drill="shopai cold-start orchestrate",
    )


def _probe_review_request() -> HealthRow:
    from engines.review_request import ReviewRequestEngine
    result = ReviewRequestEngine().run({
        "data": {"action": "status"},
    })
    data = result.get("data") or {}
    esp_ready = data.get("esp_ready", False)
    return HealthRow(
        engine="review_request",
        verdict="ready" if esp_ready else "partial",
        detail=("ESP wired"
                if esp_ready
                else "needs ESP (wires through email_connect)"),
        drill="shopai reviews status",
    )


def _probe_warmup_plan() -> HealthRow:
    from engines.warmup_plan import WarmupPlanEngine
    result = WarmupPlanEngine().run({
        "data": {"action": "phases"},
    })
    ok = result.get("status") == "success"
    return HealthRow(
        engine="warmup_plan",
        verdict="ready" if ok else "error",
        drill="shopai warmup-plan",
    )


def _probe_today_brief() -> HealthRow:
    from engines.today_brief import TodayBriefEngine
    result = TodayBriefEngine().run({})
    ok = result.get("status") == "success"
    return HealthRow(
        engine="today_brief",
        verdict="ready" if ok else "error",
        drill="shopai today",
    )


def _probe_earnings_by_engine() -> HealthRow:
    from engines.earnings_by_engine import (
        EarningsByEngineEngine,
    )
    result = EarningsByEngineEngine().run({})
    ok = result.get("status") == "success"
    return HealthRow(
        engine="earnings_by_engine",
        verdict="ready" if ok else "error",
        drill="shopai earnings-by-engine",
    )


# ── Dispatch table ────────────────────────────────────────


def collect_health(
    *, store_id: str | None = None,
) -> list[HealthRow]:
    """Run every W963 engine probe + return the list of rows."""
    probes: list[tuple[str, Callable[[], HealthRow]]] = [
        (
            "revenue_readiness",
            lambda: _probe_revenue_readiness(store_id),
        ),
        ("product_sourcer", _probe_product_sourcer),
        ("earn_bootstrap", _probe_earn_bootstrap),
        (
            "earnings_report",
            lambda: _probe_earnings_report(store_id),
        ),
        ("content_publisher", _probe_content_publisher),
        ("ads_launcher", _probe_ads_launcher),
        ("email_connect", _probe_email_connect),
        ("affiliate_links", _probe_affiliate_links),
        (
            "pinterest_publisher",
            lambda: _probe_social_platform(
                "pinterest_publisher",
            ),
        ),
        ("cro_variants", _probe_cro_variants),
        (
            "tiktok_publisher",
            lambda: _probe_social_platform(
                "tiktok_publisher",
            ),
        ),
        ("customer_chat", _probe_customer_chat),
        (
            "cold_start_orchestrator",
            _probe_cold_start_orchestrator,
        ),
        (
            "instagram_publisher",
            lambda: _probe_social_platform(
                "instagram_publisher",
            ),
        ),
        ("review_request", _probe_review_request),
        ("warmup_plan", _probe_warmup_plan),
        ("today_brief", _probe_today_brief),
        ("earnings_by_engine", _probe_earnings_by_engine),
    ]
    return [_safe_probe(name, fn) for name, fn in probes]


def summarise(rows: list[HealthRow]) -> dict[str, int]:
    """Return per-verdict counts."""
    counts = {
        "ready": 0, "partial": 0,
        "missing": 0, "error": 0,
    }
    for r in rows:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    return counts


def overall_verdict(rows: list[HealthRow]) -> str:
    """Return overall verdict based on per-verdict counts.
    ready (>= 80% ready) > partial > missing > error."""
    if not rows:
        return "missing"
    counts = summarise(rows)
    total = len(rows)
    if counts.get("error", 0) > 0:
        return "error"
    if counts.get("missing", 0) > 0:
        return "missing"
    ready_pct = counts.get("ready", 0) / total
    if ready_pct >= 0.8:
        return "ready"
    return "partial"


def first_drill(rows: list[HealthRow]) -> str:
    """Return drill hint for the first non-ready row."""
    for r in rows:
        if r.verdict != "ready" and r.drill:
            return r.drill
    return ""
