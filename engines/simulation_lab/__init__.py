"""Simulation Lab Engine — pre-execution testing laboratory.

Pipeline: scenario → simulate → predict → compare → select.

Usage:
    from engines.simulation_lab import SimulationLabEngine

    engine = SimulationLabEngine()
    result = engine.run(input_payload)
"""
from .flow import SimulationLabEngine

__all__ = ["SimulationLabEngine"]
