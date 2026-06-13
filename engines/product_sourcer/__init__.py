"""Product Sourcer Engine — cold-start product candidate generator.

A freshly-connected Shopify store has 0 products. Every autonomy
domain reads SHOPIFY_LIST_PRODUCTS — so the empty catalog quietly
disables the entire engine fleet. revenue_readiness flags this as
the highest-priority gap; this engine fills it.

Diagnostic output, NOT a Shopify writer. Returns N curated product
candidates (name + description + category + price range + tags)
matched to the operator's niche. The operator reviews + approves;
a future Phase 2 will wire SHOPIFY_CREATE_PRODUCT (status=DRAFT)
behind the approval queue.

Public API:
    ProductSourcerEngine().run({"data": {"niche": "beauty",
                                          "count": 20}})

CLI: `shopai product-candidates --niche beauty [--count 20] [--json]`
"""
from .flow import ProductSourcerEngine

__all__ = ["ProductSourcerEngine"]
