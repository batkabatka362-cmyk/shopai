"""Earn-Bootstrap Engine — W963-5.

One-command operator-facing chain that ties the W963 family
together:

    shopai earn-bootstrap --niche beauty [--count 20] [--yes]

What it does (read-only by default):
    1. Runs revenue-readiness diagnostic.
    2. Picks the highest-priority missing gate.
    3. For has_products: enumerates product candidates via
       product_sourcer. With --yes, enqueues them to the
       approval queue. Without --yes, only previews.
    4. Returns a concrete next-action summary + the diagnostic
       verdict + the queued count.

The chain stops at queue-enqueue. Operator-side approval +
Shopify-side ACTIVE transition stay manual — those are the steps
where a human MUST review what an AGI just decided to publish.
That keeps the safety gates from the rest of the substrate in
place.
"""
from .flow import EarnBootstrapEngine

__all__ = ["EarnBootstrapEngine"]
