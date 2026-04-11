"""Meta-Intelligence Governance System — the system's control brain.

Monitors all engine activity, checks rules, validates decisions,
controls risk, and prevents the system from making mistakes.

Usage:
    from engines.meta_governance import MetaGovernanceEngine

    engine = MetaGovernanceEngine()
    result = engine.run(input_payload)
"""
from .flow import MetaGovernanceEngine

__all__ = ["MetaGovernanceEngine"]
