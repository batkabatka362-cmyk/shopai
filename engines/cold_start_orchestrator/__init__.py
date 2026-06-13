"""Cold Start Orchestrator — W963-14.

End-to-end autonomous bootstrap that chains every W963 substrate
into a single operator-facing command. Where earn-bootstrap
(W963-5) only seeds products, this orchestrator runs the FULL
day-1 chain:

  1. revenue-readiness  -- diagnose current state
  2. product-candidates -- seed products if missing (W963-2)
  3. blog-candidates    -- seed SEO content if missing (W963-6)
  4. cro variants       -- generate variants for first product
  5. Status report on ads / email / social readiness
  6. Earnings snapshot

The orchestrator is READ-MOSTLY by default. Mutating actions
(product seed, blog seed) opt in via --yes. Status checks for
ads/email/social platforms are always read-only.

This is the engine an operator runs on day 1, day 2, day 7 to
get a one-screen "what should I do next?" view.

CLI:
  shopai cold-start orchestrate --store X --niche beauty [--yes]
                                 [--blog-id <GID>] [--json]
"""
from .flow import ColdStartOrchestratorEngine

__all__ = ["ColdStartOrchestratorEngine"]
