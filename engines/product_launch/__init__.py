"""Product Launch orchestrator engine.

Takes a ranked winner (from :mod:`engines.winning_products`) plus
optional supplier product + creative pack and emits a complete
*launch plan spec*: sourcing summary, pricing math, Shopify
product draft, and ads campaign draft — ready for semi-auto
approval and downstream execution.

See :mod:`engines.product_launch.flow` for the public
``run`` entry point.
"""
from .flow import ENGINE_NAME, ProductLaunchEngine, run

__all__ = ["ENGINE_NAME", "ProductLaunchEngine", "run"]
