"""Capability executor -- in-process invocation of a
registered capability.

Why this exists (per the north-star bible)
------------------------------------------
The registry tells AI what capabilities exist. The planner
tells AI which capabilities fit a goal. This module is the
NEXT compound: AI (or operator) actually INVOKES a chosen
capability and gets a result back.

Execution today is single-step + in-process: parse
``module_path`` ("module:attr"), import via importlib, call
with caller-provided kwargs, capture result or exception.
Multi-step orchestration + cross-capability piping is
deferred to the LLM-driven planner (future).

Safety
------
Plan steps with placeholder values (``<NAME>``, ``<NICHE>``)
are NOT auto-resolved here. The caller is responsible for
providing concrete args. The executor:

  - Refuses on unknown capability name.
  - Refuses when module_path doesn't parse.
  - Wraps the invocation in try/except so a raise becomes
    an ExecutionResult(ok=False, error=...), not a crash.
  - Never modifies the args dict in-place.

The CLI surface (``shopai capabilities run <name> --args
'{...}'``) defaults to dry-run; ``--yes`` opts in to real
execution. Dry-run prints the resolved module + function +
args without invoking.
"""
from __future__ import annotations

from .executor import (
    CapabilityExecutor,
    ExecutionResult,
    execute_capability,
)

__all__ = [
    "CapabilityExecutor",
    "ExecutionResult",
    "execute_capability",
]
