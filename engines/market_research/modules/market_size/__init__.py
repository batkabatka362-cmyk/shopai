"""Market Size module — TAM/SAM/SOM estimation."""
from .code import full_market_size, estimate_tam, estimate_sam, estimate_som
from .logic import decide_market_entry, required_scale
from .rules import evaluate_rules
from .data import MarketSizeRecord, get_category_growth, get_category_margin, project_market_size
from .knowledge import get_category_insight, get_heuristics, recommend_niche
