"""Winning Products engine.

Aggregates records from every ads-spy source the operator has
configured, dedupes by target product, scores each unique
product on winning-product signals (days_running, engagement
velocity, source-count, country reach, price fit), and returns
the top-K candidates with verdict + rationale.

See :mod:`engines.winning_products.flow` for the public ``run``
entry point.
"""
from .flow import ENGINE_NAME, WinningProductsEngine, run

__all__ = ["ENGINE_NAME", "WinningProductsEngine", "run"]
