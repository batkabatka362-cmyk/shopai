"""W963-121: per-store profit-and-loss substrate.

Joins W963-118 adapter-call costs with revenue
attribution to produce per-store P&L. Answers the
operator's "is store_a actually profitable?" question
directly.

Each snapshot includes:
  - spend_usd: total adapter cost over window
  - revenue_usd: total order revenue (from Shopify)
  - attributed_revenue_usd: revenue attributable to ANY
    engine cluster (the AGI-attributed portion)
  - profit_usd: revenue - spend
  - margin_pct: profit / revenue (when revenue > 0)
  - roas_ratio: revenue / spend (when spend > 0)
  - state: thriving / healthy / breakeven / losing / cold

CLI: shopai pnl [--store X] [--window-hours N]
Plus surfaced inline in empire dashboard.
"""
from .flow import PerStorePnLEngine
from .snapshot import (
    PnLState,
    StorePnLSnapshot,
    compute_fleet_snapshot,
    compute_snapshot,
)

__all__ = [
    "PerStorePnLEngine",
    "StorePnLSnapshot",
    "PnLState",
    "compute_snapshot",
    "compute_fleet_snapshot",
]
