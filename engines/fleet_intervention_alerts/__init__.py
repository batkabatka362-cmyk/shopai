"""Fleet Intervention Alerts Engine — W963-40.

Aggregates critical signals across the fleet into one
prioritized operator alert list. Combines:

  - cross_store_anomaly_detector outliers above threshold
  - fleet_strategist verdict=intervene stores
  - autopilot per-store error verdicts
  - paused autonomy domains
  - quarantined engines per store

Output: ranked list of operator-actionable interventions
with store + signal + severity + suggested drill command.

Different from fleet_strategist (W963-35) which ranks
EVERY store. This engine surfaces ONLY stores needing
intervention NOW. At 20-store scale, operator sees ONLY
the firefight, not the full list.

Bible scoring:
  Q1 (20-store leverage): at scale, operator burden = O(M)
     where M = stores with real problems. Often M << N.
  Q4 (resilience): aggregates the resilience signals from
     W963-32/33/34/38 into one operator surface.

CLI:
  shopai interventions                   -- all critical
  shopai interventions --top 5
  shopai interventions --json
"""
from .flow import FleetInterventionAlertsEngine

__all__ = ["FleetInterventionAlertsEngine"]
