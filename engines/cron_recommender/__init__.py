"""Cron Recommender — W963-59 (Phase 4 ops).

Analyzes cycle_history + verdict timeline + queue activity
+ ad-spend log to recommend an OPTIMAL cron interval. The
existing `shopai cycle schedule` emits a hardcoded 1h cron;
this proposes a TUNED interval based on observed signal
velocity.

Recommendation logic:
  - Empty empire (0 cycles)        -> hourly  (kick-start)
  - 0 actions executed per cycle   -> 4h      (waste reduce)
  - Verdict drift < N/24h          -> daily   (low activity)
  - Verdict transitions >= 2/24h   -> hourly  (high churn)
  - Anomalies detected             -> hourly  (close gap)
  - Cycles failed >= 25%           -> 2h      (avoid loop)
  - Otherwise stable               -> 2h      (default)

Output: interval_hours + reason + cron_line +
windows_systemd_template.

Pattern J + Pattern Q.

CLI:
  shopai cron-recommend [--json]
"""
from .flow import CronRecommenderEngine

__all__ = ["CronRecommenderEngine"]
