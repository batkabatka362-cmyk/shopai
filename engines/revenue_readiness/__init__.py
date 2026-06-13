"""Revenue Readiness Engine.

Diagnostic-only engine that examines a connected Shopify store
and reports which of the 6 revenue-readiness gates it passes:

  1. has_products             — catalog populated
  2. has_orders_recent        — any orders in last 30 days
  3. has_active_customers     — customer base seeded
  4. has_attributed_revenue   — Phase 8 loop has data
  5. has_ad_spend_path        — ads adapter wired + recent spend
  6. has_repeat_purchase      — at least one returning customer

Output is the standard {status, data, meta, error} envelope
(Pattern Q) with ``data.verdict`` summarising the gates and
``data.next_action`` carrying the highest-impact CLI command to
fix the lowest-passed gate.

This engine writes NOTHING. Safe to run on any connected store.
"""
from .flow import RevenueReadinessEngine

__all__ = ["RevenueReadinessEngine"]
