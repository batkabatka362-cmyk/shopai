"""Selection Decision Engine — final product selection with confidence scoring.

Orchestrates the full selection pipeline:
  score_aggregator -> ranking -> confidence_calculator -> comparison -> final_selector

Takes scored products from all upstream engines and produces a definitive
product selection with confidence rating, comparison analysis, decision
rationale, and concrete action plan.
"""
from .engine import SelectionDecisionEngine

__all__ = ["SelectionDecisionEngine"]
