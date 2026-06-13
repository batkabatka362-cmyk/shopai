"""Today Brief Engine — W963-18.

The morning operator companion. Given current store state,
emits a single 5-line "what do I do RIGHT NOW" view.

Synthesises across:
  - warmup-plan day-of action (W963-17)
  - revenue_readiness verdict (W963-1)
  - autonomy alerts (Phase 12-17 substrate)
  - approval queue head (cross-cutting)
  - last cycle status (cycle substrate)

This is the cold-start operator's morning first-touch. Designed
to be cron-friendly: 5 lines max, exit code 0 == healthy, 1 ==
operator action required.

CLI:
  shopai today                       -- text view
  shopai today --json                -- raw envelope
  shopai today --day N --niche X     -- assume specific day
  shopai today --store STORE         -- per-store scope
"""
from .flow import TodayBriefEngine

__all__ = ["TodayBriefEngine"]
