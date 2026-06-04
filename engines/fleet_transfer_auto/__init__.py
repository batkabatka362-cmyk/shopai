"""Fleet Transfer Auto Engine — W963-27.

Cross-store auto-learning hook. Scans the empire for transfer
candidates (winners on source A that target B hasn't tried) and
enqueues them as PENDING in target B's approval queue. Operator
reviews via existing approval queue but no longer manually
scans store pairs.

Scores on the bible questions:
  - Q1 (20-store leverage): each winner found compounds across
    N-1 other stores automatically
  - Q2 (substrate composability): composes _transfer_scanner +
    ApprovalQueue.enqueue + active_store + niche-compat
    classifier
  - Q3 (AGI self-learning): system propagates winners without
    operator pair-by-pair scanning

Safety
------
Multiple defense-in-depth gates:
  - Default OFF: SHOPAI_FLEET_TRANSFER_AUTO=1 required to
    actually enqueue
  - Per-pair cap (default 5): can't blast more than K transfers
    per (source, target) per invocation
  - Same-niche only by default (cross-niche needs explicit
    opt-in)
  - Min positive outcomes threshold (default 3): unproven
    winners stay manual
  - Duplicate detection: never re-enqueue same
    (engine, action_type) on the same target store

CLI:
  shopai fleet-transfer-auto                 -- dry-run preview
  shopai fleet-transfer-auto --yes           -- live enqueue
  shopai fleet-transfer-auto --min-positive 5
  shopai fleet-transfer-auto --max-per-pair 3
  shopai fleet-transfer-auto --allow-cross-niche
  shopai fleet-transfer-auto --json
"""
from .flow import FleetTransferAutoEngine

__all__ = ["FleetTransferAutoEngine"]
