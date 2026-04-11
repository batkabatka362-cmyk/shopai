"""Meta-Intelligence Governance System — the system's control brain.

Monitors all engine activity, checks rules, validates decisions,
controls risk, and prevents the system from making mistakes.

Usage:
    from engines.meta_governance import MetaGovernanceEngine

    engine = MetaGovernanceEngine()
    result = engine.run(input_payload)

Wave 2 #1 adds a tiered :class:`PolicyStore` on top of the
hardcoded ``policy_checker`` safety batch. The existing
``MetaGovernanceEngine`` pipeline is unchanged; the new
:func:`evaluate_tiered` helper gives callers access to
HARD / MEDIUM / SOFT rule evaluation with audit logging and
rule promotion::

    from engines.meta_governance import (
        PolicyTier, PolicyVerdict, PolicyRule, evaluate_tiered,
    )

    decision = evaluate_tiered(action, context)
    if decision.verdict == PolicyVerdict.BLOCK:
        ...
"""
from .flow import MetaGovernanceEngine
from .policy_store import (
    PolicyDecision,
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
    evaluate_tiered,
    get_default_store,
    reset_default_store,
)

__all__ = [
    "MetaGovernanceEngine",
    "PolicyDecision",
    "PolicyRule",
    "PolicyStore",
    "PolicyTier",
    "PolicyVerdict",
    "evaluate_tiered",
    "get_default_store",
    "reset_default_store",
]
