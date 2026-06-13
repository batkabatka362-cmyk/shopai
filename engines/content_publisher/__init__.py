"""Content Publisher Engine — W963-6.

Generates SEO-targeted blog post candidates for a niche and
optionally enqueues them as DRAFT articles to Shopify via the
approval queue. Mirrors product_sourcer (W963-2/3) pattern.

Why this matters for cold-start stores:
  - A new Shopify store has 0 traffic. Paid ads cost money + need
    credentials. Email marketing needs an existing customer list.
  - SEO blog content is FREE, compounds over time (each post can
    rank in Google for months/years), and gets indexed within
    days of publication.
  - Each blog post is a doorway for organic search traffic that
    feeds into the W963-1 has_orders_recent gate downstream.

The engine writes NOTHING by default. Read-only candidate
generation; --apply opt-in routes through the approval queue.
Articles are always DRAFT/unpublished — operator must explicitly
publish them. This keeps a human in the loop for first content
publish even when the rest of the cycle is autonomous.

CLI:
  shopai blog-candidates --niche beauty [--count 10] [--apply] [--json]
"""
from .flow import ContentPublisherEngine

__all__ = ["ContentPublisherEngine"]
