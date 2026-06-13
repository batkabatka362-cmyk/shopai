"""Revenue Reconciliation Engine — W963-47 (Phase 3.A capstone).

Honest accounting: distinguishes AGI-attributed revenue from
organic + catches orphan attribution claims. Without this, the
"earning autonomously" claim is unverifiable.

Three buckets per order:
  1. ATTRIBUTED — order has at least one plausible EXECUTED
     action (right engine type, decided BEFORE order, within
     attribution window). Real AGI revenue.
  2. ORGANIC — order with NO matching action. Operator direct,
     direct traffic, or social organic. NOT AGI.
  3. ORPHAN_ACTION — EXECUTED action claiming revenue with NO
     matching order. Possible false positive in claim or
     order webhook missed.

Bible scoring:
  Q1 (20-store leverage): operator needs honest signal of
     which stores the AGI is actually moving vs riding
     organic. At 20-store scale this is the difference
     between scaling the right thing and scaling vanity.
  Q4 (resilience): orphan claims = bug. Surfaces them so
     they can be investigated.

Default-OFF for any auto-correction; engine is READ-ONLY
report unless --apply is supplied (and even then env-gated).

CLI:
  shopai reconcile                       -- fleet report
  shopai reconcile --store STORE         -- single store
  shopai reconcile --days 7
  shopai reconcile --json
"""
from .flow import RevenueReconciliationEngine

__all__ = ["RevenueReconciliationEngine"]
