"""ROAS Guardrails engine.

Consumes campaign performance metrics and emits kill / scale /
hold decisions per campaign based on ROAS (Return on Ad Spend)
thresholds with learning-phase protection.

See :mod:`engines.roas_guardrails.flow` for the public ``run``
entry point.
"""
from .flow import ENGINE_NAME, RoasGuardrailsEngine, run

__all__ = ["ENGINE_NAME", "RoasGuardrailsEngine", "run"]
