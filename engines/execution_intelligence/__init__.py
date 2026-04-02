"""Execution Intelligence Engine — action execution pipeline.

Pipeline: parse → validate → select tools → route → execute → collect → report.

Usage:
    from engines.execution_intelligence import ExecutionIntelligenceEngine

    engine = ExecutionIntelligenceEngine()
    result = engine.run(input_payload)
"""
from .flow import ExecutionIntelligenceEngine

__all__ = ["ExecutionIntelligenceEngine"]
