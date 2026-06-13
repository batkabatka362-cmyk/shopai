"""Cross-Store Anomaly Detector — W963-33.

Per-store metric divergence detector. Computes fleet-wide
norms (median + MAD) for key metrics across all stores, then
flags stores whose value diverges N+ MADs from the median.

Metrics monitored (default):
  - 7d_revenue          (from earnings_by_engine)
  - earning_engine_count
  - funnel_drop_rate    (from conversion_funnel)
  - approval_pending    (queue depth)
  - checkup_partial_count

Bible scoring:
  Q1 (20-store leverage): operator can't manually compare 20
     stores; this engine surfaces "store X is the outlier"
     automatically.
  Q4 (resilience): catches degradation that single-store
     diagnostics miss (e.g. one store's funnel is fine in
     isolation but 5x worse than fleet median).

CLI:
  shopai anomaly-detect                   -- all stores
  shopai anomaly-detect --mad 3.0         -- stricter threshold
  shopai anomaly-detect --metric revenue  -- single metric
  shopai anomaly-detect --json
"""
from .flow import CrossStoreAnomalyDetectorEngine

__all__ = ["CrossStoreAnomalyDetectorEngine"]
