"""Customer Segmentation Engine — actionable customer grouping.

Segments customers into actionable groups based on behavior, value,
lifecycle stage, and purchase patterns. Produces segments with
marketing strategies attached.

Usage:
    from engines.customer_segmentation import CustomerSegmentationEngine

    engine = CustomerSegmentationEngine()
    result = engine.run(input_payload)
"""
from .flow import CustomerSegmentationEngine

__all__ = ["CustomerSegmentationEngine"]
