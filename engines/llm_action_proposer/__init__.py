"""LLM Action Proposer — W963-52 (Phase 3.B middle).

Composes the empire's CURRENT state into 3 ranked next-actions
with rationale + CLI command. Distinct from
core.capability_planner.llm_planner (which seeds from NL
goals); this proposer reads CURRENT state and answers
"what should I do RIGHT NOW?"

Inputs read:
  - W963-48 agi_earnings_summary verdict
  - W963-50 agi_earnings_history latest snapshot
  - approval queue pending count
  - Phase 8 attribution snapshot (top cluster)

Consultant pattern (Wave 17/24/34/49/W963-51):
  1. Deterministic baseline ALWAYS proposes 3 actions
     based on verdict + signals.
  2. LLM is OPT-IN via SHOPAI_AI_STRATEGY=1 + OPENAI_API_KEY.
  3. LLM is asked to REFINE the rationale strings only.
     It cannot remove or invent actions.
  4. Invalid LLM response -> baseline preserved.

Pattern J guard.

CLI:
  shopai next-actions
  shopai next-actions --store STORE
  shopai next-actions --json
"""
from .flow import LlmActionProposerEngine

__all__ = ["LlmActionProposerEngine"]
