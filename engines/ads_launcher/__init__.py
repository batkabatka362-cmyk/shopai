"""Ads Launcher Engine — W963-7.

Operator-facing wrapper around the Meta/Google Ads adapters. The
adapters expose raw Marketing-API capabilities (create_campaign,
update_budget, pause). This engine bundles them into the day-1
operator experience:

  shopai ads status              -- what's connected?
  shopai ads connect <platform>  -- credentials setup helper
  shopai ads launch [--platform meta] [--budget-daily 10]
                                 -- fire the first PAUSED campaign

Every launched campaign is created with status=PAUSED. The
operator MUST go to Meta/Google Ads Manager to:
  1. Add ad sets + creative + audience targeting
  2. Review the budget + objective
  3. Activate the campaign

This keeps a human in the loop for the first real-money write
even when the W963 chain is otherwise autonomous. The same
substrate that Wave 47 spend caps + Wave 112 budget guardrails
already monitor will pick up the campaign once active.

Read-only by default (status command); --apply on launch
commits to the platform API.
"""
from .flow import AdsLauncherEngine

__all__ = ["AdsLauncherEngine"]
