"""Welcome Series Engine — W963-22.

When a customer registers, fires a 3-email welcome cadence:
  - email 1 (immediate): brand intro + first-order discount
  - email 2 (day 2): top-3 best-seller showcase
  - email 3 (day 5): user-generated content / review prompts

Drives first-order conversion (industry data: welcome emails
have 4-5x the open rate of standard campaigns) and repeat-
buyer behavior.

Mirrors review_request's shape: pull recent customers via
SHOPIFY_FETCH_CUSTOMERS, filter who's already been welcomed,
dispatch each email at its scheduled cadence via the wired
ESP. Pattern J test guard + Pattern Z record_writeback on
every send.

CLI:
  shopai welcome status                    -- ESP wired? welcomed count?
  shopai welcome preview --limit N         -- next batch of N
  shopai welcome send-batch [--yes]        -- dispatch (default dry-run)
"""
from .flow import WelcomeSeriesEngine

__all__ = ["WelcomeSeriesEngine"]
