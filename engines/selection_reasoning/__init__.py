"""Selection Reasoning Engine — explains WHY a product was selected.

The final engine in the product selection flow. Orchestrates five modules:
  narrative_builder -> data_citation -> risk_disclosure -> alternative_presenter -> action_planner

Takes the selection decision output and all engine results, then produces
a complete reasoning report with narrative explanation, supporting citations,
transparent risk disclosure, alternative comparisons, and a concrete
action plan.
"""
from .engine import SelectionReasoningEngine

__all__ = ["SelectionReasoningEngine"]
