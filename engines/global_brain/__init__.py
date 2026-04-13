"""Global Brain Engine — collective knowledge system.

Ingests outputs from all engines, extracts knowledge, detects patterns,
stores knowledge, and provides context back to engines.

Usage:
    from engines.global_brain import GlobalBrainEngine

    engine = GlobalBrainEngine()
    result = engine.run(input_payload)
"""
from .flow import GlobalBrainEngine

__all__ = ["GlobalBrainEngine"]
