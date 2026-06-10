"""W963-119: per-store quota tracking + alerting substrate.

Reads spend from W963-118's per-store cost log and joins
with operator-defined budget caps. Surfaces three kinds
of alerts to operator:

  - warn:     spend has crossed 70% of cap (configurable)
  - critical: spend has crossed 100% of cap
  - blocked:  caller checked + cap was exceeded -> action
              should be blocked

Used by:
  - shopai quota CLI: human-readable + JSON output
  - autopause bridge: when cycle hook runs, autopause
    spend-class engines for stores at critical
  - api-status / earn-readiness: surface budget pressure

Caps are resolved with the same per-store override chain
as W963-116's credential helper:

  1. SHOPAI_STORE_<SID>_<ADAPTER>_DAILY_BUDGET_USD
     -- most specific: per-store, per-adapter cap
  2. SHOPAI_STORE_<SID>_DAILY_BUDGET_USD
     -- per-store total budget across all adapters
  3. <ADAPTER>_DAILY_BUDGET_USD
     -- fleet-wide per-adapter cap
  4. SHOPAI_DAILY_BUDGET_USD
     -- fleet-wide total cap

Empty / unset / 0.0 means unlimited. The tracker honours
the most specific cap that resolves to a positive value.
"""
from .autopause import (
    AutopauseAction,
    AutopauseReport,
    maybe_autopause,
)
from .budget_config import (
    resolve_cap,
    resolve_warn_ratio,
)
from .flow import PerStoreQuotaEngine
from .tracker import (
    QuotaSnapshot,
    QuotaState,
    compute_all_snapshots,
    compute_snapshot,
    critical_stores,
    warn_stores,
)

__all__ = [
    "PerStoreQuotaEngine",
    "QuotaSnapshot",
    "QuotaState",
    "AutopauseAction",
    "AutopauseReport",
    "compute_all_snapshots",
    "compute_snapshot",
    "critical_stores",
    "warn_stores",
    "maybe_autopause",
    "resolve_cap",
    "resolve_warn_ratio",
]
