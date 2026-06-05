"""AGI Anomaly Detector — W963-57 (Phase 4 watchdog).

Scans the W963-50 history snapshot timeline + W963-44
outcome backfill records for SUDDEN statistical anomalies.
Different from regression detection (chronic decline over a
window): this catches single-day spikes/drops the operator
should know about immediately.

Detection dimensions:
  - VERDICT_FLIP: latest verdict differs from rolling mode
    of last N snapshots.
  - PROFIT_OUTLIER: latest gross_profit > MAD threshold
    (median absolute deviation) of last N.
  - ATTRIBUTION_COLLAPSE: latest attribution_pct dropped
    >= 50% absolute from rolling median.
  - ATTRIBUTION_SPIKE: rose >= 50% absolute.
  - ORPHAN_BURST: orphan_action_count jumped from <=2 to
    >=10 since the prior snapshot.

Returns a list of Anomaly records, each with type +
severity + delta + explanation. Empty list = clean.

Pattern J + Pattern Q.

CLI:
  shopai anomalies [--window N] [--json]
"""
from .flow import AgiAnomalyDetectorEngine

__all__ = ["AgiAnomalyDetectorEngine"]
