"""Store P&L Tracker — W963-45.

Per-store profit & loss tracker. Computes:

  revenue        = sum of Shopify order totals (window)
  ad_spend       = sum of cost-bearing approval queue actions
                   tagged ads / marketing
  refunds        = sum of refunds in window
  esp_spend      = sum of email-send actions × per-send cost
  shipping_cost  = approximation from order shipping_lines
                   (when present)

  gross_revenue  = revenue
  net_revenue    = revenue - refunds
  total_cost     = ad_spend + esp_spend + shipping_cost
  gross_profit   = net_revenue - total_cost
  margin_pct     = gross_profit / net_revenue × 100

This is the substrate that makes "earning autonomously" a
measurable claim. Without P&L, "the store is earning" =
"revenue > 0" which ignores ad spend.

Bible scoring:
  Q1 (20-store leverage): operator scans P&L across N stores
     to know which are actually profitable vs vanity-revenue.
  Q4 (resilience): unprofitable stores surface in dashboard
     before they bleed too much.

CLI:
  shopai pnl                       -- per-store + fleet
  shopai pnl --store STORE         -- single store drill
  shopai pnl --days 7              -- window
  shopai pnl --json
"""
from .flow import StorePnlTrackerEngine

__all__ = ["StorePnlTrackerEngine"]
