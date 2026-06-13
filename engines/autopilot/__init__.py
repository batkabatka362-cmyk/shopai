"""Autopilot Engine — W963-23.

Single-command autonomous loop. Composes the 4 highest-leverage
W963 substrate pieces into one cron-friendly action:

  1. welcome_series — fire any due 3-email welcome cadence
  2. review_request — fire any eligible post-purchase asks
  3. earnings_by_engine — record measurement snapshot
  4. checkup — verify substrate health post-run

Designed for: cron / scheduled task / one-button autonomous
operation. Each step is env-gated so an operator can disable
specific writers without touching code:

  SHOPAI_AUTOPILOT_WELCOME=1     (default OFF — sends emails)
  SHOPAI_AUTOPILOT_REVIEWS=1     (default OFF — sends emails)
  SHOPAI_AUTOPILOT_MEASURE=1     (default ON  — read-only)
  SHOPAI_AUTOPILOT_HEALTH=1      (default ON  — read-only)

Default ON for read-only stages so the operator can preview the
loop before opting in to writers. Default OFF for write stages
so accidental invocation can't blast emails.

CLI:
  shopai autopilot                 -- dry-run preview
  shopai autopilot --yes           -- live, but each stage still
                                       respects its env-gate
  shopai autopilot --store STORE   -- per-store scope
  shopai autopilot --json          -- machine-readable
"""
from .flow import AutopilotEngine

__all__ = ["AutopilotEngine"]
