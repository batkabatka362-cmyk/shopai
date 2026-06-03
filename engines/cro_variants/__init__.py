"""CRO Variants Engine — W963-11.

Given a Shopify product, generate 2-3 alternative versions of:

  - title:    different angles (feature / benefit / urgency)
  - description: different copy strategies (short / value-prop /
                 social-proof)
  - price:    suggested test points (current / -10% / +15%)

Output is a structured variant report the operator can A/B test
via Shopify's theme + their preferred experiment tool. The
existing engines.ab_testing module handles experiment design +
statistical analysis once the operator runs the variants.

This engine writes NOTHING. Read-only candidate generator.
A future Phase 2 will wire variant publishing via
SHOPIFY_UPDATE_PRODUCT (with the variant's title/desc) behind
the approval queue.

CLI:
  shopai cro variants --product-id gid://shopify/Product/X
                       [--strategies title,description,price]
                       [--json]
"""
from .flow import CroVariantsEngine

__all__ = ["CroVariantsEngine"]
