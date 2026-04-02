"""Time Intelligence Engine — the system's timing brain.

Pipeline: classify -> prioritize -> resolve deps -> estimate -> schedule -> queue -> trigger -> track.

Usage:
    from engines.time_intelligence import TimeIntelligenceEngine

    engine = TimeIntelligenceEngine()
    result = engine.run(input_payload)
"""
from .flow import TimeIntelligenceEngine

__all__ = ["TimeIntelligenceEngine"]
