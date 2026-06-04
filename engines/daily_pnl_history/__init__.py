"""Daily P&L History Engine — W963-46.

Persistent daily P&L snapshots. Without this, W963-45
store_pnl_tracker only shows today's number. With this,
operator can ask "are we trending up?", LLM brain can read
"this engine's recommendations historically led to +N%
profit growth", and the empire-AGI has a longitudinal
signal.

Composes:
  - W963-45 store_pnl_tracker compute_store_pnl
  - JSON-backed rolling history (Pattern J test guard)
  - Per-store trend computation

Bible scoring:
  Q1 (20-store leverage): operator can see "across N stores,
     which are GROWING profit vs sliding".
  Q3 (AI self-learning): LLM brain queries history before
     recommending. "We tried this last month -- did it help?"
  Q4 (resilience): falling P&L surfaces as trend BEFORE the
     point estimate hits negative.

CLI:
  shopai pnl-history                       -- summary
  shopai pnl-history --record              -- snapshot now
  shopai pnl-history --store STORE         -- per-store trend
  shopai pnl-history --days 30
  shopai pnl-history --json
"""
from .flow import DailyPnlHistoryEngine

__all__ = ["DailyPnlHistoryEngine"]
