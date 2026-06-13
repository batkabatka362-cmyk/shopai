"""Fleet Autopilot Engine — W963-26.

Iterates autopilot (W963-23) across every store in the fleet,
aggregates per-store results into a single fleet-wide verdict.
THE substrate piece that turns 1-operator into "1 operator +
20+ stores in parallel" — the North Star.

Each store runs in its own active_store(sid) thread-local
context so cross-store side effects (Pattern Z record_writeback
tagging, approval queue store_id, alert quarantine scope) stay
correctly partitioned per-store.

CLI:
  shopai fleet-autopilot                  -- dry-run, all stores
  shopai fleet-autopilot --yes            -- live (still
                                             env-gated per writer)
  shopai fleet-autopilot --skip-store X   -- exclude one
  shopai fleet-autopilot --only-store X   -- run just one
  shopai fleet-autopilot --json           -- machine-readable

Compounds with:
  - autopilot (W963-23) — per-store loop substrate
  - transfer_scan / transfer_apply — cross-store winners
  - active_store thread-local — pattern Y per-store partitioning
  - approval queue store_id — per-store approval scope
"""
from .flow import FleetAutopilotEngine

__all__ = ["FleetAutopilotEngine"]
