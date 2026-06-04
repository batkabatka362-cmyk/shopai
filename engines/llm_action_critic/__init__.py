"""LLM Action Critic — W963-53 (Phase 3.B closer).

Adversarial critique of the W963-52 action_proposer output.
Where the proposer answers "what should we do?", the critic
asks "what could go wrong with that?"

Pairs propose / critique to give the operator a fuller view.

Deterministic baseline draws from known anti-patterns:
  - cycle-run-without-fixing-failure
  - batch-approve when verdict=organic_only
  - bootstrap on a store without credentials
  - tighten spend caps without checking pending ads
  - transfer-scan with insufficient outcome history

LLM may REFINE the counter_rationale strings only. Cannot
remove or invent flags.

Consultant pattern + Pattern J + Pattern Q.

CLI:
  shopai action-critic [--store STORE] [--json]
"""
from .flow import LlmActionCriticEngine

__all__ = ["LlmActionCriticEngine"]
