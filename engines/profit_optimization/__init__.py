"""Profit Optimization Engine — the money-growing brain.

Continuously analyzes revenue, costs, profit, finds optimization
opportunities, and recommends actions to maximize ROI.

Usage:
    from engines.profit_optimization import ProfitOptimizationEngine

    engine = ProfitOptimizationEngine()
    result = engine.run(input_payload)
"""
from .flow import ProfitOptimizationEngine

__all__ = ["ProfitOptimizationEngine"]
