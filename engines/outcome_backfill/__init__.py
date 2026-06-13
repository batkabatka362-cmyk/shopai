"""Outcome Backfill Engine — W963-44.

Closes the outcome-feedback loop. EXECUTED approval queue
actions sit in "unknown" outcome state until something matches
them to real Shopify revenue. This engine:

  1. Lists EXECUTED actions in the queue
  2. For actions decided >= N hours ago without recorded outcome:
     - Pulls Shopify orders created after action.decided_at
     - Records "positive" outcome with attributed revenue if
       orders exist for that (store, action_type) pair
     - Records "negative" outcome if elapsed > grace_period
       with zero matching orders

The feedback flows back through:
  - queue.record_outcome → engine_outcome_stats
  - W963-29 confidence_auto_approver uses the stats
  - W963-39 confidence_calibrator computes bands
  - W963-43 strategist_memory can refresh outcomes
  - W963-19 earnings_by_engine attributes revenue

Bible scoring:
  Q1 (20-store leverage): without this, every engine's track
     record stays "unknown" forever. The 20-store empire can't
     compound trust without backfill.
  Q3 (AI self-learning): this IS the feedback signal. Other
     engines READ outcomes; this engine WRITES them.
  Q4 (resilience): degrading engines surface in stats sooner,
     calibrator bands them as "cautious"/"blocked" sooner.

Safety
------
Triple-gated:
  - default dry-run
  - --yes required
  - SHOPAI_OUTCOME_BACKFILL_ENABLED=1 env required
  - Per-action only updates ONCE (idempotent on already-recorded)

CLI:
  shopai outcome-backfill                          -- dry-run
  shopai outcome-backfill --yes                    -- live
  shopai outcome-backfill --min-age-hours 24
  shopai outcome-backfill --grace-hours 168
  shopai outcome-backfill --store STORE
  shopai outcome-backfill --json
"""
from .flow import OutcomeBackfillEngine

__all__ = ["OutcomeBackfillEngine"]
