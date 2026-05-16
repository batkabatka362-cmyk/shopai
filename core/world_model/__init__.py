"""Per-store world model.

A single dict that captures everything an AI orchestrator needs
to know about a store at decision time. Read-only.

The world model is the foundation for the AGI orchestration
layer -- engines and the autonomous loop read a snapshot before
making decisions instead of running N separate queries. The
snapshot is also the unit of "what was the state when we
decided?" for after-the-fact analysis.

Sections:

  - store_id / fetched_at: identification + freshness
  - store: shop_url, niche, store_type, is_active
  - stats: products / orders / customers / revenue
  - sync: last_sync_at + status + age_seconds
  - connection: live probe (skippable)
  - config: drift count from configurator dry_run (skippable)
  - design: store_design engine's conversion-lift estimate
  - approvals: pending action counts (GLOBAL -- no per-store
    column on pending_actions yet)
  - decisions: recent decision-log entries (GLOBAL)

Each section carries a ``checked`` flag so consumers can tell
the difference between "checked and empty" and "skipped".
"""
from __future__ import annotations

from .snapshot import WorldModel, snapshot

__all__ = ["WorldModel", "snapshot"]
