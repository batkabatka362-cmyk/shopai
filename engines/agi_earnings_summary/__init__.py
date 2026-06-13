"""AGI Earnings Summary — W963-48 (Phase 3.A polish).

Composes the three Phase 3.A substrate engines into one
operator-readable answer to: "Is the AGI earning?"

Combines:
  - reconcile_fleet (W963-47): attributed vs organic split
  - compute_fleet_pnl (W963-45): gross profit per store
  - compute_trend (W963-46): rising/falling/flat verdict
    when history exists

Output: a single verdict band
  earning           AGI attributed revenue > 0 AND
                    gross_profit > 0
  attributed_loss   AGI attributed revenue > 0 BUT
                    gross_profit < 0 (overspending on ads)
  organic_only      Some revenue but 0% attributed to AGI
  no_data           Empire idle

CLI:
  shopai earnings-summary
  shopai earnings-summary --days 7
  shopai earnings-summary --json
"""
from .flow import AgiEarningsSummaryEngine

__all__ = ["AgiEarningsSummaryEngine"]
