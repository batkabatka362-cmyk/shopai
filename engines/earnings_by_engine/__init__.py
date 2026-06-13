"""Earnings By Engine — W963-19.

Joins the W963 cold-start engine roster to per-engine revenue
attribution. Tells the operator: "of the 18 W963 engines you
have wired, which fired this week and which produced
attributable revenue?"

This is the operator-facing accountability layer the warmup-plan
(W963-17) opens — knowing what to fire is different from knowing
what worked.

CLI:
  shopai earnings-by-engine [--window-hours N] [--store X] [--json]
"""
from .flow import EarningsByEngineEngine

__all__ = ["EarningsByEngineEngine"]
