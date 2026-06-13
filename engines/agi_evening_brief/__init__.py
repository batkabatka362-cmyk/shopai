"""AGI Evening Brief — W963-55 (Phase 4 complement).

End-of-day complement to W963-54 morning_brief. Where the
morning brief answers "what should I do?", the evening brief
answers "what happened today?"

Composes (24h window):
  - cycle_history runs            -> count + success rate
  - approval queue executed       -> committed action count
  - outcome_backfill results      -> outcome decisions today
  - agi_earnings_summary delta    -> end-of-day verdict
  - agi_earnings_history latest   -> verdict drift since AM

One screen. Pattern J + Pattern Q.

CLI:
  shopai evening-brief [--store STORE] [--json]
"""
from .flow import AgiEveningBriefEngine

__all__ = ["AgiEveningBriefEngine"]
