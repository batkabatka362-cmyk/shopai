"""Checkup Engine — W963-21.

Diagnostic across the entire W963 cold-start chain. Calls each
of the 18 engines' status action (or equivalent) in-process,
collects verdicts, emits a single per-engine health table.

Different from bigpicture (W963-20) which is the morning ROUTINE
view. Checkup is a diagnostic across the whole stack — "which
engines are wired vs broken vs not-yet-connected".

CLI:
  shopai checkup                  -- full table across 18 engines
  shopai checkup --store STORE    -- per-store scope
  shopai checkup --json           -- machine-readable
"""
from .flow import CheckupEngine

__all__ = ["CheckupEngine"]
