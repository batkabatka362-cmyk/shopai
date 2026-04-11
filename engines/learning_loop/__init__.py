"""Learning Loop Engine — the system's learning brain.

Pipeline: collect -> evaluate -> detect -> analyze -> insight -> improve -> write -> feedback.

Usage:
    from engines.learning_loop import LearningLoopEngine

    engine = LearningLoopEngine()
    result = engine.run(input_payload)
"""
from .flow import LearningLoopEngine

__all__ = ["LearningLoopEngine"]
