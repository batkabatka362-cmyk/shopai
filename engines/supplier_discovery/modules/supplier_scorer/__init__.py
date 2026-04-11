"""Supplier Scorer module — score and rank suppliers on reliability, quality, price, communication."""
from .code import score_supplier
from .logic import compare_suppliers, recommend_supplier, build_supplier_shortlist
from .rules import evaluate_rules, RULES
from .data import DIMENSION_WEIGHTS, RED_FLAG_INDICATORS, COUNTRY_RISK_SCORES
from .knowledge import get_negotiation_tips, get_inspection_checklist, get_scam_guide
