"""W963-149: brand identity composer.

Phase 2 substrate of the 100-store ramp. The operator
described 'store setup-iig AI hiinee' which requires
ShopAI to autonomously compose:

  - Color palette (primary / secondary / accent /
    text / background)
  - Typography (heading font / body font)
  - Logo brief (style + tagline)
  - Logo concepts (multiple candidates via image gen)
  - Hero / banner image candidates (Pexels + AI)

Pattern matches W963-143 product proposal:
  1. ShopAI runs LLM + image adapters to compose
  2. Generates a markdown brief + image refs
  3. Submits ONE approval action (action_type
     'apply_brand_identity')
  4. Operator approves the brief
  5. Dispatcher pushes choices to Shopify
     (theme settings + logo upload + hero images)

Fail-soft: each step degrades gracefully when its
adapter is missing. Operator sees diagnostic notes
inline.
"""
from .composer import (
    BrandBrief,
    ColorPalette,
    Typography,
    build_brief,
    brief_to_markdown,
)
from .flow import BrandIdentityComposerEngine

__all__ = [
    "BrandIdentityComposerEngine",
    "BrandBrief",
    "ColorPalette",
    "Typography",
    "build_brief",
    "brief_to_markdown",
]
