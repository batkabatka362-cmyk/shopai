"""Budget plan runner — fetch ad performance + run allocator.

One autopilot cycle call produces one budget plan:

    1. Call ``Capability.ADS_GET_PERFORMANCE`` via router
       (Meta Ads today; any ads adapter registered in future
       works the same way).
    2. Parse each campaign's name + actions to extract the
       product_handle (SKU proxy) + orders + spend. Naming
       convention set by ``execution/launch/publisher_bundle.
       _step_launch_campaign``:

           shopai:<decision_id[:10]>:<product_handle[:32]>

    3. Aggregate by SKU (one SKU may have multiple campaigns
       across launch attempts — sum their spend + orders).
    4. Build :class:`SKUPerformance` records + run the
       Thompson allocator.
    5. Save the plan to ``reports/budget_plans/<ts>.json`` —
       owner reviews + applies via CLI/MCP (risk-gated).
    6. Return a ``PlanReport`` so the autopilot cycle can
       record counts on its CycleSummary.

READ-ONLY at Meta's side. We don't push the recommended
budget back — that's a HIGH action per risk_gate and owner
drives the apply flow manually (for now). Wire-up of an
auto-apply path via approval_queue is a future commit.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from core.engines.budget_buyer.allocator import (
    BudgetAllocation, BudgetAllocator, SKUPerformance,
)

_logger = logging.getLogger(
    "shopai.budget_buyer.plan_runner",
)

# Publisher_bundle's campaign name — defined here (not
# imported) so the runner stays decoupled from the launch
# pipeline module.
#
#   shopai:<decision_id[:10]>:<product_handle[:32]>
_NAME_RE = re.compile(
    r"^shopai:(?P<decision>[a-zA-Z0-9]+):"
    r"(?P<handle>[a-zA-Z0-9_\-]+)$",
)

#: Default window for the perf fetch. Matches BudgetAllocator's
#: Thompson prior which assumes a rolling window rather than
#: lifetime numbers.
_DEFAULT_DATE_PRESET = "last_7d"

#: Action types the conversion counter looks at (Meta's
#: taxonomy is noisy; accept any of these as a "purchase
#: event").
_PURCHASE_ACTION_TYPES = (
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "onsite_web_purchase",
    "omni_purchase",
)


@dataclass
class PlanReport:
    """Outcome of one ``run_budget_plan`` call."""

    plan_id: str = ""
    date: str = ""
    campaigns_seen: int = 0
    skus_planned: int = 0
    total_daily_usd: float = 0.0
    allocations: list[BudgetAllocation] = field(default_factory=list)
    plan_path: str = ""
    error: str = ""
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "date": self.date,
            "campaigns_seen": self.campaigns_seen,
            "skus_planned": self.skus_planned,
            "total_daily_usd": round(self.total_daily_usd, 2),
            "allocations": [
                a.as_dict() for a in self.allocations
            ],
            "plan_path": self.plan_path,
            "error": self.error,
            "skipped": self.skipped,
        }


# ── Parsing helpers (pure) ──────────────────────────────


def _parse_campaign_name(name: str) -> tuple[str, str]:
    """Return ``(decision_id, product_handle)`` extracted from
    a publisher-bundle campaign name. Non-matching names return
    ``("", "")`` — runner filters them out (owner's manual
    campaigns stay out of the Thompson plan)."""
    if not name:
        return "", ""
    m = _NAME_RE.match(name.strip())
    if not m:
        return "", ""
    return m.group("decision"), m.group("handle")


def _purchase_count(actions: Any) -> int:
    """Sum purchase-like action counts from Meta's ``actions``
    list. Meta sometimes returns the count as a string — coerce
    defensively."""
    if not isinstance(actions, list):
        return 0
    total = 0
    for row in actions:
        if not isinstance(row, dict):
            continue
        if row.get("action_type") in _PURCHASE_ACTION_TYPES:
            try:
                total += int(float(row.get("value", 0) or 0))
            except (TypeError, ValueError):
                continue
    return total


def _aggregate_to_skus(
    campaigns: list[dict[str, Any]],
    *,
    avg_order_value_usd: float,
    days_active: int,
) -> tuple[list[SKUPerformance], int]:
    """Group Meta campaigns by extracted product_handle, sum
    orders + spend. Revenue approximated as ``orders ×
    avg_order_value_usd`` (Meta doesn't return per-order value
    in the performance endpoint; the allocator only needs a
    relative ROAS signal so this is acceptable).

    Returns ``(sku_records, unmatched_count)`` — caller can
    log how many campaigns didn't fit the naming convention.
    """
    by_sku: dict[str, dict[str, Any]] = {}
    unmatched = 0

    for camp in campaigns:
        if not isinstance(camp, dict):
            continue
        _decision, handle = _parse_campaign_name(
            str(camp.get("campaign_name") or ""),
        )
        if not handle:
            unmatched += 1
            continue
        try:
            spend = float(camp.get("spend", 0) or 0)
        except (TypeError, ValueError):
            spend = 0.0
        try:
            impressions = int(camp.get("impressions", 0) or 0)
        except (TypeError, ValueError):
            impressions = 0
        try:
            clicks = int(camp.get("clicks", 0) or 0)
        except (TypeError, ValueError):
            clicks = 0
        orders = _purchase_count(camp.get("actions"))

        bucket = by_sku.setdefault(handle, {
            "orders": 0, "spend": 0.0,
            "impressions": 0, "clicks": 0,
        })
        bucket["orders"] += orders
        bucket["spend"] += spend
        bucket["impressions"] += impressions
        bucket["clicks"] += clicks

    records: list[SKUPerformance] = []
    for handle, agg in by_sku.items():
        records.append(SKUPerformance(
            sku=handle,
            orders=int(agg["orders"]),
            revenue_usd=float(agg["orders"] * avg_order_value_usd),
            ad_spend_usd=float(agg["spend"]),
            impressions=int(agg["impressions"]),
            clicks=int(agg["clicks"]),
            days_active=max(1, int(days_active)),
        ))
    return records, unmatched


# ── Plan persistence ────────────────────────────────────


def _write_plan(
    allocations: list[BudgetAllocation],
    *,
    plan_id: str,
    total_daily_usd: float,
    campaigns_seen: int,
    unmatched: int,
    reports_dir: str = "reports/budget_plans",
) -> str:
    """Serialise the plan to JSON. Returns the written path."""
    os.makedirs(reports_dir, exist_ok=True)
    payload = {
        "plan_id": plan_id,
        "generated_at": (
            _dt.datetime.now(_dt.timezone.utc).isoformat()
        ),
        "total_daily_usd": round(total_daily_usd, 2),
        "campaigns_seen": campaigns_seen,
        "campaigns_unmatched": unmatched,
        "allocations": [a.as_dict() for a in allocations],
    }
    path = os.path.join(reports_dir, f"{plan_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


# ── Main runner ─────────────────────────────────────────


def run_budget_plan(
    *,
    total_daily_usd: float | None = None,
    min_per_sku_usd: float | None = None,
    max_per_sku_usd: float | None = None,
    avg_order_value_usd: float | None = None,
    date_preset: str = _DEFAULT_DATE_PRESET,
    router: Any = None,
    reports_dir: str = "reports/budget_plans",
    seed: int | None = None,
) -> PlanReport:
    """Fetch ads performance, run allocator, persist plan.

    Every arg has an env-var default so the autopilot cycle
    can call ``run_budget_plan()`` with no args:

      * ``total_daily_usd``      ← SHOPAI_TOTAL_DAILY_BUDGET_USD
      * ``min_per_sku_usd``      ← SHOPAI_BUDGET_MIN_PER_SKU (0)
      * ``max_per_sku_usd``      ← SHOPAI_BUDGET_MAX_PER_SKU (no cap)
      * ``avg_order_value_usd``  ← SHOPAI_AVG_ORDER_VALUE_USD (35)

    Returns a ``PlanReport``. Skipped silently (``skipped=True``)
    when total budget is 0 or no adapter configured — autopilot
    treats this as a normal no-op cycle.
    """
    report = PlanReport()

    # Resolve config from env with defaults
    if total_daily_usd is None:
        try:
            total_daily_usd = float(
                os.environ.get(
                    "SHOPAI_TOTAL_DAILY_BUDGET_USD", 0,
                ) or 0,
            )
        except (TypeError, ValueError):
            total_daily_usd = 0.0
    if total_daily_usd <= 0:
        report.skipped = True
        report.error = (
            "SHOPAI_TOTAL_DAILY_BUDGET_USD unset or zero — "
            "skipping plan"
        )
        return report

    if min_per_sku_usd is None:
        try:
            min_per_sku_usd = float(
                os.environ.get(
                    "SHOPAI_BUDGET_MIN_PER_SKU", 0,
                ) or 0,
            )
        except (TypeError, ValueError):
            min_per_sku_usd = 0.0
    if max_per_sku_usd is None:
        try:
            max_env = float(
                os.environ.get(
                    "SHOPAI_BUDGET_MAX_PER_SKU", 0,
                ) or 0,
            )
            max_per_sku_usd = max_env if max_env > 0 else None
        except (TypeError, ValueError):
            max_per_sku_usd = None
    if avg_order_value_usd is None:
        try:
            avg_order_value_usd = float(
                os.environ.get(
                    "SHOPAI_AVG_ORDER_VALUE_USD", 35.0,
                ) or 35.0,
            )
        except (TypeError, ValueError):
            avg_order_value_usd = 35.0

    # Resolve router lazily so runner import works in a
    # reduced-dep deploy.
    if router is None:
        try:
            from core.adapters import get_router
            router = get_router()
        except Exception as exc:  # noqa: BLE001
            report.skipped = True
            report.error = f"router unavailable: {exc}"
            return report

    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        report.skipped = True
        report.error = f"Capability enum unavailable: {exc}"
        return report

    try:
        perf_result = router.execute(
            Capability.ADS_GET_PERFORMANCE,
            {
                "date_preset": date_preset,
                "level": "campaign",
                "fields": (
                    "campaign_name,impressions,spend,"
                    "clicks,actions"
                ),
            },
        )
    except Exception as exc:  # noqa: BLE001
        report.skipped = True
        report.error = f"insights fetch raised: {exc}"
        return report

    if not perf_result.ok:
        report.skipped = True
        report.error = (
            f"insights not ok: "
            f"{getattr(perf_result, 'error', 'unknown')}"
        )
        return report

    campaigns = (perf_result.data or {}).get("campaigns") or []
    report.campaigns_seen = len(campaigns)
    if not campaigns:
        report.skipped = True
        report.error = "no campaigns in insights window"
        return report

    # Days active: parse date_preset like "last_7d"
    days_active = _days_from_preset(date_preset)
    perf_records, unmatched = _aggregate_to_skus(
        campaigns,
        avg_order_value_usd=avg_order_value_usd,
        days_active=days_active,
    )
    if not perf_records:
        report.skipped = True
        report.error = (
            f"no campaigns matched publisher naming pattern "
            f"(all {unmatched} skipped)"
        )
        return report

    allocator = BudgetAllocator(seed=seed)
    allocations = allocator.allocate(
        total_daily_usd, perf_records,
        min_per_sku_usd=min_per_sku_usd,
        max_per_sku_usd=max_per_sku_usd,
    )

    plan_id = _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%d-%H%M%S",
    )
    plan_path = _write_plan(
        allocations, plan_id=plan_id,
        total_daily_usd=total_daily_usd,
        campaigns_seen=len(campaigns),
        unmatched=unmatched,
        reports_dir=reports_dir,
    )

    report.plan_id = plan_id
    report.date = plan_id[:10]
    report.skus_planned = len(allocations)
    report.total_daily_usd = total_daily_usd
    report.allocations = allocations
    report.plan_path = plan_path
    return report


def _days_from_preset(preset: str) -> int:
    """Parse ``last_7d`` / ``last_30d`` / ``last_14d`` into an
    int day count. Defaults to 7 for anything unrecognised."""
    m = re.match(r"last_(\d+)d", preset or "")
    if m:
        try:
            return max(1, int(m.group(1)))
        except (TypeError, ValueError):
            return 7
    return 7


def list_plans(
    reports_dir: str = "reports/budget_plans",
    *, limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the last ``limit`` plan files (newest first)."""
    if not os.path.isdir(reports_dir):
        return []
    files = sorted(
        (f for f in os.listdir(reports_dir)
         if f.endswith(".json")),
        reverse=True,
    )[:max(1, int(limit))]
    out: list[dict[str, Any]] = []
    for fn in files:
        path = os.path.join(reports_dir, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        payload["_path"] = path
        out.append(payload)
    return out
