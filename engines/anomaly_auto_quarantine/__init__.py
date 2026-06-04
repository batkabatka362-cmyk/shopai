"""Anomaly Auto-Quarantine Engine — W963-38.

When cross_store_anomaly_detector (W963-33) flags an outlier
above severity threshold, this engine auto-pauses that store's
writers via the existing per-store quarantine substrate
(core.approval.quarantine.add_alert_pause).

Closes the resilience loop:
  cross_store_anomaly → detects outlier
  anomaly_auto_quarantine → halts writers on that store
  operator → reviews + manually releases (or auto-release)

Bible scoring:
  Q1 (20-store leverage): single command halts the bad store
     across 20 without operator manually pausing each engine.
  Q4 (resilience): canonical reactive defense -- system halts
     the diverging store automatically, contains the blast.

Safety
------
Triple-gated:
  - default dry-run
  - --yes required
  - SHOPAI_ANOMALY_AUTO_QUARANTINE=1 env required
  - --min-deviation threshold (default 4.0 MADs, higher than
    cross_store_anomaly's default 3.0 so we're conservative)

Per-engine pause list:
  - Default: only autopilot writers (welcome_series,
    review_request) since they're the highest-volume real-
    money paths
  - --engine X repeatable for more

CLI:
  shopai anomaly-quarantine                    -- dry-run
  shopai anomaly-quarantine --yes              -- live pause
  shopai anomaly-quarantine --min-deviation 5
  shopai anomaly-quarantine --engine X --engine Y
  shopai anomaly-quarantine --json
"""
from .flow import AnomalyAutoQuarantineEngine

__all__ = ["AnomalyAutoQuarantineEngine"]
