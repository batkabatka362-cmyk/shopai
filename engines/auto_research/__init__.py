"""Auto Research Engine — knowledge gathering pipeline.

query → search → extract → filter → analyze → synthesize

Usage::

    from engines.auto_research import AutoResearchEngine

    engine = AutoResearchEngine()
    result = engine.run({
        "query": "e-commerce pricing strategies 2025",
        "context": "mid-tier online retail",
        "max_sources": 10,
        "depth": "standard",
    })
"""
from .flow import AutoResearchEngine

__all__ = ["AutoResearchEngine"]
