"""core.reflection — error-pattern mining and soft-rule promotion.

Exposes :class:`ReflectionSynthesizer` for the controller's
post-tick hook and tests that want to run the miner directly.
"""
from __future__ import annotations

from core.reflection.synthesizer import (
    ErrorPattern,
    ReflectionSynthesizer,
    SynthesisReport,
)

__all__ = [
    "ErrorPattern",
    "ReflectionSynthesizer",
    "SynthesisReport",
]
