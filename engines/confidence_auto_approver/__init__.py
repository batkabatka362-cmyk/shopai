"""Confidence Auto-Approver Engine — W963-29.

Trust-wedge widener. When an engine's per-store track record
crosses a threshold (≥N actions, ≥X% positive), future PENDING
actions of the same (engine, action_type) get auto-approved.
Reduces operator review burden in proportion to AI trust.

This is the AGI-merchant's "earn-the-keys" loop:
  - Start: every action needs operator approval
  - Engine A produces 5 positive outcomes
  - Engine A's future actions of same type auto-approve
  - Operator only reviews engines that haven't earned trust
  - At 20-store scale, ~90% of PENDING actions auto-approve

Scores on bible:
  Q1 (20-store leverage): operator review burden drops as
     trust accrues; at scale, only outliers need attention.
  Q3 (AI self-learning): the trust threshold IS the learning
     loop -- system observes outcomes + grants more autonomy
     to engines that earn it.
  Q4 (resilience): a degrading engine's trust falls below
     threshold automatically, falling back to operator review.

Safety
------
Triple-gated:
  - Default OFF: SHOPAI_CONFIDENCE_AUTO_APPROVE=1 required
  - Per-engine minimum_sample (default 5)
  - Per-engine positive_ratio threshold (default 0.8)
  - --yes flag still required to actually approve

CLI:
  shopai auto-approve                      -- dry-run preview
  shopai auto-approve --yes                -- live approve
  shopai auto-approve --min-positive-ratio 0.9
  shopai auto-approve --min-sample 10
  shopai auto-approve --store STORE        -- per-store scope
  shopai auto-approve --json
"""
from .flow import ConfidenceAutoApproverEngine

__all__ = ["ConfidenceAutoApproverEngine"]
