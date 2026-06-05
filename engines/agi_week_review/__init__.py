"""AGI Week Review — W963-56 (Phase 4 macro).

7-day aggregator complementing the morning (W963-54) +
evening (W963-55) primitives. Macro-loop view: instead of
"what should I do today?" or "what happened today?", this
answers "how did the week go?"

Composes (7d default window):
  - cycle_history.recent_runs       -> total cycles +
                                       success rate trend
  - approval queue                  -> total actions
                                       executed + rejection rate
  - agi_earnings_history snapshots  -> verdict-by-day
                                       timeline + verdict
                                       transitions count
  - revenue_reconciliation.reconcile_fleet
                                    -> 7d AGI attribution
                                       share + orphan total

Headline summarises week verdict: "growing" /
"stable_earning" / "stable_organic" / "regressing" /
"recovering" / "quiet" based on snapshot timeline.

Pattern J + Pattern Q.

CLI:
  shopai week-review [--days N] [--store STORE] [--json]
"""
from .flow import AgiWeekReviewEngine

__all__ = ["AgiWeekReviewEngine"]
