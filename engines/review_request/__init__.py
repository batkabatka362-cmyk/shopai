"""Review Request Engine — W963-16.

Post-purchase review request automation. Pulls recently delivered
orders via SHOPIFY_FETCH_ORDERS, filters out orders already asked,
generates a niche-aware review request email, and sends via the
configured ESP (Brevo / Resend via W963-8).

Why this matters
----------------
Product reviews are the highest-leverage conversion driver for
e-commerce — a 4.5-star average can lift conversion 15-30% over
a no-review baseline. Most stores fail at gathering reviews
because they never ASK. ShopAI automates the ask.

Flow:
  1. Pull orders from configurable window (default 7-30 days
     after delivery is the conversion sweet spot)
  2. Filter out orders already asked (in-memory tracking
     defaults; future: Shopify metafield persistence)
  3. For each remaining order: generate per-customer email
  4. Dispatch via SEND_EMAIL_TRANSACTIONAL through email_connect

Read-only by default; --send commits. Always records via
Pattern Z so the autonomous loop sees outcomes.

CLI:
  shopai reviews status                       -- ESP wired? recent orders?
  shopai reviews preview --limit N            -- show the next N requests
  shopai reviews send-batch [--limit N]       -- dispatch (env-gated)
"""
from .flow import ReviewRequestEngine

__all__ = ["ReviewRequestEngine"]
