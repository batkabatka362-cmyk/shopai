"""Daily Trajectory Engine — W963-24.

Daily revenue + order-count + per-day delta chart across the
last N days. Closes the operator's most important diagnostic
question: "are we trending up?"

earnings (W963-4) gives a single-window snapshot. earnings-by-
engine (W963-19) shows attribution per engine. Neither answers
"is the slope positive?". This engine binnings orders into
calendar days and computes day-over-day delta.

CLI:
  shopai trajectory                    -- last 30 days
  shopai trajectory --days 14          -- shorter window
  shopai trajectory --store STORE      -- per-store
  shopai trajectory --json             -- machine-readable
"""
from .flow import DailyTrajectoryEngine

__all__ = ["DailyTrajectoryEngine"]
