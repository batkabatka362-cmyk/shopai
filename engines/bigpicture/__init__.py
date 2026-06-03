"""Bigpicture Engine — W963-20.

One-command unified morning view. Replaces the 3-command
morning routine (today + earnings-by-engine + warmup-plan
--day N) with a single rendered screen.

Calls each underlying engine in-process, no shell roundtrip.
Each section is best-effort: if one substrate is unavailable,
the other sections still render.

CLI:
  shopai bigpicture                       -- one-command morning
  shopai bigpicture --day N --niche X     -- assume specific day
  shopai bigpicture --store STORE         -- per-store scope
  shopai bigpicture --json                -- machine-readable
"""
from .flow import BigpictureEngine

__all__ = ["BigpictureEngine"]
