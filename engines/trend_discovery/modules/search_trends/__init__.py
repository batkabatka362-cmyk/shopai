"""Search Trends module — keyword trend analysis and opportunity detection."""
from .code import analyze_search_trends
from .logic import decide_keyword_pursuit, cluster_keywords, rank_keyword_opportunities
from .rules import evaluate_rules
from .data import get_keyword_difficulty_info, get_category_cpc, KEYWORD_DIFFICULTY
from .knowledge import get_keyword_strategy, get_heuristics
