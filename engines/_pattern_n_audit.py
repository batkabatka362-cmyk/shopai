"""Pattern N audit: niche-merge preservation across orchestrator
strategies.

Wave 89 found + fixed a silent bug: ``AIOrchestratorStrategy``
dropped the niche merge when the LLM reclassified the priority
class. The unit tests didn't catch it because they only asserted
``priority`` and didn't compare ``cluster_focus``.

The bug class generalizes -- any orchestrator strategy wrapper
that rebuilds StorePriority from base clusters risks silently
losing niche bias. Pattern N is a runtime audit that probes
every loadable OrchestratorStrategy implementation with a
niched store + asserts the result preserves the niche merge.

Concretely: for each strategy, run decide_priority with a
synthetic beauty-niche store. The result's cluster_focus[0:3]
must include at least one of beauty's top clusters
(merchandising / content / retention). If not, the wrapper
dropped the merge.

Violations are surfaced as PatternNViolation rows. CI gate +
operator command ``shopai pattern-n-audit`` consume the
report.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Strategies live in this module
_STRATEGY_PACKAGES = (
    "engines._orchestrator",
    "engines._ai_strategies",
    "engines._revenue_aware_orchestrator",
)

# Synthetic beauty-niche world_model used to probe each strategy
_BEAUTY_WORLD_MODEL: dict[str, Any] = {
    "store": {
        "store_id": "pattern-n-probe",
        "niche": "beauty",
    },
    "stats": {
        "products": 50,
        "orders": 30,
        "total_revenue": 5000.0,
    },
}

# Top niche clusters for beauty (any of these in cluster_focus
# top-3 means the merge survived)
_BEAUTY_TOP_CLUSTERS = frozenset({
    "merchandising", "content", "retention",
})


@dataclass
class PatternNViolation:
    strategy_class: str
    cluster_focus: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PatternNReport:
    strategies_probed: list[str] = field(default_factory=list)
    violations: list[PatternNViolation] = field(default_factory=list)
    probe_errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _is_orchestrator_strategy(obj: Any) -> bool:
    """Check whether obj looks like an OrchestratorStrategy --
    duck-typed on the decide_priority method."""
    if not inspect.isclass(obj):
        return False
    if obj.__name__.startswith("_"):
        return False
    method = getattr(obj, "decide_priority", None)
    if method is None or not callable(method):
        return False
    # Skip the Protocol class itself
    try:
        if obj.__module__ == "typing":
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


def _instantiate_strategy(cls: Any) -> Any | None:
    """Try to construct the strategy with no args. Wrapper
    strategies that need a base get the deterministic
    orchestrator as their inner."""
    try:
        return cls()
    except TypeError:
        # Wrapper strategies need a base. Try with the
        # deterministic orchestrator.
        try:
            from engines._orchestrator import (
                DeterministicOrchestratorStrategy,
            )
            return cls(base=DeterministicOrchestratorStrategy())
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Pattern N: %s instantiation failed: %s",
                cls.__name__, exc,
            )
            return None
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern N: %s instantiation raised: %s",
            cls.__name__, exc,
        )
        return None


def _probe_strategy(
    cls: Any, report: PatternNReport,
) -> None:
    instance = _instantiate_strategy(cls)
    if instance is None:
        report.probe_errors.append({
            "strategy_class": cls.__name__,
            "reason": "instantiation_failed",
        })
        return
    try:
        priority = instance.decide_priority(
            "pattern-n-probe", _BEAUTY_WORLD_MODEL,
        )
    except Exception as exc:  # noqa: BLE001
        report.probe_errors.append({
            "strategy_class": cls.__name__,
            "reason": f"decide_priority raised: {exc}",
        })
        return
    focus = getattr(priority, "cluster_focus", None) or []
    if not isinstance(focus, list):
        focus = []
    # Check top-3 for a beauty cluster
    top3 = focus[:3]
    if not any(c in _BEAUTY_TOP_CLUSTERS for c in top3):
        report.violations.append(PatternNViolation(
            strategy_class=cls.__name__,
            cluster_focus=focus,
            reason=(
                "beauty niche merge missing from top-3 "
                f"of cluster_focus={focus}"
            ),
        ))


def _scan_module(module_name: str, report: PatternNReport) -> None:
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        report.probe_errors.append({
            "strategy_class": module_name,
            "reason": f"import failed: {exc}",
        })
        return
    for name, obj in inspect.getmembers(mod):
        if not _is_orchestrator_strategy(obj):
            continue
        # Skip if defined elsewhere (re-imported)
        if getattr(obj, "__module__", "") != module_name:
            continue
        # Skip if it's a Protocol/abstract -- look for it
        # being NOT in the strategy's own __mro__ chain
        report.strategies_probed.append(name)
        _probe_strategy(obj, report)


def run_pattern_n_audit() -> PatternNReport:
    """Probe every orchestrator strategy + return the report."""
    report = PatternNReport()
    for module_name in _STRATEGY_PACKAGES:
        _scan_module(module_name, report)
    return report
