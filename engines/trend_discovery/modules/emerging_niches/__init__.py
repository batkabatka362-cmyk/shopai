"""Emerging Niches module — detect new niches before they become mainstream."""
from .code import discover_emerging_niches
from .logic import assess_niche_viability, estimate_niche_timeline, recommend_entry_timing
from .rules import evaluate_niche_rules
from .data import get_emerging_niches, SIGNAL_WEIGHTS, NICHE_LIFECYCLE_STAGES
from .knowledge import get_niche_heuristics, get_validation_playbook
