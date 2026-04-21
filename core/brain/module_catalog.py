"""Brain module catalog — honest labelling of the 225-module
brain tree so orphans are declared, not denied.

Why this exists (audit batch 4, §4d "сул хэсэг → reconnect,
not remove"): 41 modules in ``core/brain/`` have 0 callers
today. A silent orphan is worse than a declared one:

  * an orphan you don't know about looks like a broken
    feature when someone later expects it to run;
  * an orphan you *have* declared as ``experimental`` tells
    the reader "this is a parked design — wire it when the
    decision flow needs it, don't rewrite it".

This registry does not change runtime behaviour. It is a
metadata layer the owner can query via MCP to see:

  * ``active``       — wired into the live decision flow
  * ``experimental`` — implemented + tested but awaiting
    orchestrator integration
  * ``archived``     — kept for reference, explicitly not
    planned for wire-up
  * ``unknown``      — modules not yet categorised (default)

Any brain module can self-declare by calling
``declare_module(name, category="experimental", reason="...")``
at import time. The registry tolerates missing / unseen
modules: `status()` returns ``("unknown", "")`` instead of
raising.

Pure stdlib. Thread-safe. No LLM.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


_VALID_CATEGORIES = (
    "active", "experimental", "archived", "unknown",
)


@dataclass(frozen=True)
class ModuleStatus:
    name: str
    category: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "reason": self.reason,
        }


class _ModuleCatalog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, ModuleStatus] = {}

    def declare(
        self, name: str, *, category: str, reason: str = "",
    ) -> ModuleStatus:
        if not name:
            raise ValueError("name required")
        if category not in _VALID_CATEGORIES:
            raise ValueError(
                f"category must be in {_VALID_CATEGORIES}",
            )
        status = ModuleStatus(
            name=name, category=category, reason=reason,
        )
        with self._lock:
            self._entries[name] = status
        return status

    def status(self, name: str) -> ModuleStatus:
        with self._lock:
            hit = self._entries.get(name)
        if hit is not None:
            return hit
        return ModuleStatus(
            name=name, category="unknown", reason="",
        )

    def by_category(
        self, category: str,
    ) -> list[ModuleStatus]:
        if category not in _VALID_CATEGORIES:
            raise ValueError(
                f"category must be in {_VALID_CATEGORIES}",
            )
        with self._lock:
            return sorted(
                (e for e in self._entries.values()
                 if e.category == category),
                key=lambda e: e.name,
            )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {
                c: 0 for c in _VALID_CATEGORIES
            }
            for e in self._entries.values():
                counts[e.category] = counts.get(
                    e.category, 0,
                ) + 1
            entries = sorted(
                (e.as_dict()
                 for e in self._entries.values()),
                key=lambda d: (
                    d["category"], d["name"],
                ),
            )
        return {
            "total_declared": len(entries),
            "by_category": counts,
            "entries": entries,
        }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._entries.clear()


_CATALOG = _ModuleCatalog()


def declare_module(
    name: str, *, category: str, reason: str = "",
) -> ModuleStatus:
    """Declare a brain module's wire-up status. Called at
    import time by orphan modules so the registry knows about
    them without changing runtime behaviour."""
    return _CATALOG.declare(
        name, category=category, reason=reason,
    )


def module_status(name: str) -> ModuleStatus:
    """Return the declared status, or ``("unknown", "")`` if
    no declaration exists."""
    return _CATALOG.status(name)


def modules_by_category(category: str) -> list[ModuleStatus]:
    return _CATALOG.by_category(category)


def catalog_summary() -> dict[str, Any]:
    return _CATALOG.summary()


def reset_catalog_for_tests() -> None:
    _CATALOG.reset_for_tests()


# ── Known orphan declarations (audit batch 4 categorisation) ─
# Each of these is fully implemented + tested but has 0 production
# callers. Categorised as ``experimental`` rather than deleted per
# §4d — when the decision flow next needs the capability we wire
# them up instead of re-inventing.
#
# Categorise as active the modules the decision flow DOES call
# directly today (a representative sample so tests verify the
# "active" bucket isn't empty).

# Experimental (wire when decision flow evolves):
declare_module(
    "ab_bandit",
    category="experimental",
    reason=(
        "Thompson-sampling action selector. Wire when "
        "brain.decide() grows a multi-variant path."
    ),
)
declare_module(
    "abstraction_ladder",
    category="experimental",
    reason=(
        "Hierarchy builder over goal decomposition. Wire "
        "when planner needs sub-goal rollout."
    ),
)
declare_module(
    "anomaly_triage",
    category="experimental",
    reason=(
        "Outlier classifier for incoming events. Wire "
        "after CrisisResponder escalates an unknown type."
    ),
)
declare_module(
    "model_coordinator",
    category="experimental",
    reason=(
        "Multi-model voting over a question. Wire when "
        "SmartRouter supports ensemble responses."
    ),
)
declare_module(
    "analogy_mapper",
    category="experimental",
    reason=(
        "Cross-domain similarity → action transfer. Wire "
        "after multi-store rule sharing ships."
    ),
)

# Active (wired into the live decision flow today):
declare_module(
    "structured_decision",
    category="active",
    reason=(
        "5-pillar Deliberation recorder. Every activator / "
        "publisher call records here; owner reads via MCP."
    ),
)
declare_module(
    "world_model_calibration",
    category="active",
    reason=(
        "Predicted-vs-actual KPI calibration. Feeds the "
        "predict_outcome MCP tool + engine_outcome_bus."
    ),
)
declare_module(
    "brain_facade",
    category="active",
    reason=(
        "Central snapshot + module registrar. Every cycle "
        "calls snapshot(); dashboards + MCP read from here."
    ),
)
