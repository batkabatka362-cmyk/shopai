"""Proposal report builder.

Chains the existing substrate:
  - product_research engine -> ad-spy + sourcing
                                  candidates
  - LLM scoring (via brain adapter) -> ranking +
                                         justification
  - Margin calculator -> projected economics
  - Plan report -> markdown summary for approval queue

Defensive imports throughout: cold-start empires +
missing optional adapters degrade gracefully.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProductCandidate:
    """One scored candidate for inclusion in the
    proposal."""
    title: str
    supplier_id: str = ""
    supplier: str = ""           # cj / autods / aliexpress
    cost_usd: float = 0.0
    suggested_retail_usd: float = 0.0
    projected_margin_pct: float = 0.0
    niche_match_score: float = 0.0   # 0-1 LLM rank
    risk_flags: list[str] = field(default_factory=list)
    reason: str = ""             # 1-sentence LLM
                                  # justification
    source_signal: str = ""      # "minea" / "pipiads"
                                  # / "trending"

    @property
    def is_actionable(self) -> bool:
        """Has enough data to import."""
        return bool(
            self.title
            and self.supplier
            and self.cost_usd > 0
        )


@dataclass
class ProposalReport:
    """Full plan report submitted to the approval queue.
    Operator approves the WHOLE batch, ShopAI imports
    everything inside."""
    store_id: str
    niche: str
    requested_count: int
    discovered_count: int
    candidates: list[ProductCandidate] = field(
        default_factory=list,
    )
    discovery_window_hours: float = 168.0
    notes: list[str] = field(default_factory=list)

    @property
    def total_inventory_cost_usd(self) -> float:
        return sum(
            c.cost_usd for c in self.candidates
        )

    @property
    def average_margin_pct(self) -> float:
        if not self.candidates:
            return 0.0
        return sum(
            c.projected_margin_pct
            for c in self.candidates
        ) / len(self.candidates)


def _safe_run_research(
    store_id: str, niche: str, count: int,
) -> list[dict[str, Any]]:
    """Best-effort: call the product_research engine to
    surface candidates. Returns empty list when the
    engine is unavailable / fails / returns no products."""
    try:
        from engines.registry import get_engine
        eng = get_engine("product_research")
        if eng is None:
            return []
        result = eng.run({
            "data": {
                "store_id": store_id,
                "niche": niche,
                "limit": count * 2,  # over-fetch
            },
        })
        if not isinstance(result, dict):
            return []
        data = result.get("data") or {}
        candidates = data.get("candidates") or data.get(
            "products",
        ) or []
        return [
            c for c in candidates
            if isinstance(c, dict)
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_research raised: %s", exc,
        )
        return []


def _safe_run_sourcing_lookup(
    candidate_title: str,
) -> dict[str, Any]:
    """Best-effort: query CJ / AutoDS adapter for
    supplier match. Returns empty dict on failure --
    candidate then surfaces with empty supplier data
    + an 'unsourced' risk flag."""
    try:
        from core.adapters.smart_router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "router unavailable for sourcing: %s", exc,
        )
        return {}
    try:
        result = router.execute(
            Capability.SOURCING_SEARCH_PRODUCT,
            {"query": candidate_title, "limit": 1},
        )
        if not result.ok:
            return {}
        data = getattr(result, "data", None) or {}
        items = data.get("products") or []
        if not items:
            return {}
        first = items[0]
        if not isinstance(first, dict):
            return {}
        return first
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "sourcing lookup raised: %s", exc,
        )
        return {}


_DEFAULT_MARKUP_MULTIPLIER = 2.8  # 280% markup =
                                   # ~64% margin


def _compute_economics(
    cost_usd: float,
) -> tuple[float, float]:
    """Return (suggested_retail, margin_pct)."""
    if cost_usd <= 0:
        return 0.0, 0.0
    retail = cost_usd * _DEFAULT_MARKUP_MULTIPLIER
    margin = (retail - cost_usd) / retail * 100.0
    return round(retail, 2), round(margin, 1)


def _gather_risk_flags(
    candidate: ProductCandidate,
    raw_data: dict[str, Any],
) -> list[str]:
    """Surface risks the operator should know:
      - Long shipping (>14 days) -> 'slow_shipping'
      - Low supplier rating -> 'unproven_supplier'
      - Price volatility flagged -> 'price_volatile'
      - Brand-protected trademark -> 'trademark_risk'
    """
    flags: list[str] = []
    if not candidate.supplier:
        flags.append("unsourced")
    ship_days = raw_data.get("avg_shipping_days") or 0
    try:
        if float(ship_days) > 14:
            flags.append("slow_shipping")
    except (TypeError, ValueError):
        pass
    rating = raw_data.get("supplier_rating") or 0
    try:
        if 0 < float(rating) < 4.0:
            flags.append("unproven_supplier")
    except (TypeError, ValueError):
        pass
    if raw_data.get("trademark_risk"):
        flags.append("trademark_risk")
    if candidate.projected_margin_pct < 30:
        flags.append("thin_margin")
    return flags


def build_proposal(
    store_id: str,
    *,
    niche: str = "",
    count: int = 10,
    window_hours: float = 168.0,
) -> ProposalReport:
    """Build the proposal report for the given store.

    Fail-soft: every adapter call can degrade. The
    returned report carries notes describing any data
    sources that were unavailable so the operator
    can decide whether to retry."""
    report = ProposalReport(
        store_id=store_id,
        niche=niche,
        requested_count=max(1, int(count)),
        discovered_count=0,
        discovery_window_hours=window_hours,
    )

    raw_candidates = _safe_run_research(
        store_id, niche, count,
    )
    if not raw_candidates:
        report.notes.append(
            "product_research engine returned no "
            "candidates -- ad-spy or sourcing adapter "
            "may be unconfigured. Run `shopai api-test "
            "--alias minea` or `shopai api-status "
            "--category sourcing` to diagnose."
        )
        return report

    report.discovered_count = len(raw_candidates)
    out: list[ProductCandidate] = []
    for raw in raw_candidates[: count * 2]:
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        supplier = str(raw.get("supplier") or "")
        cost = 0.0
        try:
            cost = float(raw.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0

        # If raw didn't include supplier data, try a
        # sourcing lookup. Cheap when the adapter is
        # configured + a no-op otherwise.
        if not supplier or cost <= 0:
            lookup = _safe_run_sourcing_lookup(title)
            if lookup:
                supplier = supplier or str(
                    lookup.get("supplier", "cj"),
                )
                if cost <= 0:
                    try:
                        cost = float(
                            lookup.get(
                                "price",
                            ) or 0.0,
                        )
                    except (TypeError, ValueError):
                        cost = 0.0

        retail, margin = _compute_economics(cost)
        candidate = ProductCandidate(
            title=title,
            supplier_id=str(
                raw.get("supplier_id") or "",
            ),
            supplier=supplier,
            cost_usd=round(cost, 2),
            suggested_retail_usd=retail,
            projected_margin_pct=margin,
            niche_match_score=float(
                raw.get("score") or 0.0,
            ),
            reason=str(raw.get("reason") or "")[:240],
            source_signal=str(
                raw.get("source") or "research",
            ),
        )
        candidate.risk_flags = _gather_risk_flags(
            candidate, raw,
        )
        out.append(candidate)

    # Rank: highest niche_match * margin, sorted desc.
    out.sort(
        key=lambda c: (
            -(c.niche_match_score * c.projected_margin_pct),
            -c.projected_margin_pct,
            c.title,
        ),
    )
    report.candidates = out[:count]

    actionable = sum(
        1 for c in report.candidates
        if c.is_actionable
    )
    if actionable < len(report.candidates):
        report.notes.append(
            f"{len(report.candidates) - actionable} "
            "candidate(s) lack sourcing data -- they "
            "are surfaced but won't auto-import unless "
            "supplier resolves at execution time."
        )
    return report


def report_to_markdown(report: ProposalReport) -> str:
    """Render proposal as markdown for the approval
    queue narrative."""
    lines: list[str] = []
    lines.append(
        f"## Product onboarding proposal"
        f"  -- store={report.store_id}"
    )
    lines.append("")
    lines.append(
        f"**Niche:** {report.niche or '(unspecified)'}"
    )
    lines.append(
        f"**Discovery window:** "
        f"{report.discovery_window_hours:.0f}h"
    )
    lines.append(
        f"**Discovered:** "
        f"{report.discovered_count} candidate(s)"
    )
    lines.append(
        f"**Proposed:** {len(report.candidates)} "
        "product(s)"
    )
    lines.append(
        f"**Total inventory cost:** "
        f"${report.total_inventory_cost_usd:.2f}"
    )
    lines.append(
        f"**Avg projected margin:** "
        f"{report.average_margin_pct:.1f}%"
    )
    lines.append("")
    if report.notes:
        lines.append("**Notes:**")
        for n in report.notes:
            lines.append(f"  - {n}")
        lines.append("")

    if not report.candidates:
        lines.append(
            "_No candidates surfaced. Approve to "
            "no-op._"
        )
        return "\n".join(lines)

    lines.append("### Candidates")
    lines.append("")
    lines.append(
        "| # | Title | Supplier | Cost | Retail | "
        "Margin | Score | Risks |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|"
    )
    for i, c in enumerate(report.candidates, start=1):
        risks = (
            ", ".join(c.risk_flags) if c.risk_flags
            else "-"
        )
        lines.append(
            f"| {i} | {c.title[:40]} | "
            f"{c.supplier or '?'} | "
            f"${c.cost_usd:.2f} | "
            f"${c.suggested_retail_usd:.2f} | "
            f"{c.projected_margin_pct:.0f}% | "
            f"{c.niche_match_score:.2f} | "
            f"{risks} |"
        )
    lines.append("")
    lines.append(
        "**Approve** to auto-import all listed "
        "candidates with their supplier data + LLM-"
        "generated descriptions + SEO meta + variant "
        "configuration. **Reject** to discard the "
        "batch (no Shopify changes)."
    )
    return "\n".join(lines)
