"""Shipping Optimization Engine — carrier selection, rate comparison, and strategy.

Optimizes shipping costs by comparing carriers, finding free-shipping
thresholds, estimating delivery times, and recommending the best strategy.

Pipeline:
  Order/Product Data → Rate Calculator → Carrier Comparator →
  Threshold Optimizer → Delivery Estimator → Cost Allocator →
  Zone Mapper → Strategy Recommender → Output

Usage:
    from engines.shipping_optimization import ShippingOptimizationEngine

    engine = ShippingOptimizationEngine()
    result = engine.run(input_payload)
"""
from .flow import ShippingOptimizationEngine

__all__ = ["ShippingOptimizationEngine"]
