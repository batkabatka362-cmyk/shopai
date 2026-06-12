"""W963-143: plan-based product onboarding proposal.

Operator clarified the approval pattern: not per-product
manual approval. Instead:

  1. ShopAI runs discovery (ad-spy + sourcing + LLM
     scoring) and identifies top N candidate products
     for the store's niche.
  2. Generates a BATCH PLAN REPORT: 'I found these
     products, here's the import plan, projected
     margins, risks.'
  3. Submits ONE approval row to the queue (action_type
     = 'propose_product_batch').
  4. Operator reviews the plan + approves the BATCH
     (single click).
  5. ShopAI auto-imports all approved products via
     SHOPIFY_CREATE_PRODUCT + per-product description /
     SEO / variant configuration.

This collapses what would have been N approvals into 1,
preserves operator's right to veto, and matches the
'AI proposes, operator approves the plan' pattern the
operator described.
"""
from .flow import ProductOnboardingProposalEngine
from .proposal import (
    ProductCandidate,
    ProposalReport,
    build_proposal,
)

__all__ = [
    "ProductOnboardingProposalEngine",
    "ProductCandidate",
    "ProposalReport",
    "build_proposal",
]
