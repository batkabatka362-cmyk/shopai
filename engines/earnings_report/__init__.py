"""Earnings Report Engine — W963-4.

Output-side measurement. Reads recent Shopify orders and computes:

  - Today's revenue (configurable window)
  - Previous-window revenue
  - % delta (growth or decline)
  - Order count
  - Average order value (AOV)
  - Per-store + fleet breakdown

The engine deliberately does NOT depend on the attribution loop
(engines._attribution_snapshot). That loop attributes revenue to
engines for the learning side; this engine answers the operator's
simpler question: "did ANY money come in?".

Read-only. Pattern Q compliant.

CLI: ``shopai earnings [--days 1] [--store X] [--json]``
"""
from .flow import EarningsReportEngine

__all__ = ["EarningsReportEngine"]
