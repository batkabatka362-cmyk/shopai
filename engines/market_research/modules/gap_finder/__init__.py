"""Gap Finder module — detect underserved niches and unmet customer needs."""
from .code import find_gaps
from .logic import decide_gap_pursuit, prioritize_gaps, gap_to_product_spec
from .rules import evaluate_rules
from .data import GapRecord, get_gap_profile, get_benchmarks, GAP_TYPE_PROFILES
from .knowledge import get_exploitation_strategy, get_review_mining_guide, get_validation_framework
