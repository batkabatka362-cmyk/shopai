"""Cross-Sell Engine — public API.

Identifies cross-sell opportunities: recommends complementary products
to increase average order value (AOV).

Exports only the CrossSellEngine orchestrator class.
"""
from .flow import CrossSellEngine

__all__ = ["CrossSellEngine"]
