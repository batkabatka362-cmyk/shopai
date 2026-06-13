"""W963-148: autonomy gate -- guards cross-store
autonomous propagation behind a proven-stable
threshold.

Operator's requirement (2026-06-12): cross-store
autonomous transfer can only unlock AFTER the first 5
stores have proven to run perfectly with zero bugs /
zero mistakes confirmed.

The gate is a READ-ONLY check that downstream callers
consult before promoting a transfer recipe from
'operator-driven' to 'autonomously propagated'. It
computes:

  - Number of stores that have run cleanly over the
    proof window
  - Per-store incident counts (cycle errors, autopause
    fires, refund anomalies, gold-bug)
  - Threshold verdict: locked / unlocked

Threshold semantics: 5 stores × N days × 0 incidents
per store (N configurable, default 30 days). Operator
can lower the bar via env vars for ramp testing or
raise it for higher confidence.
"""
from .threshold import (
    AutonomyGateReport,
    StoreStability,
    check_autonomy_gate,
    is_autonomy_unlocked,
)
from .flow import AutonomyGateEngine

__all__ = [
    "AutonomyGateEngine",
    "AutonomyGateReport",
    "StoreStability",
    "check_autonomy_gate",
    "is_autonomy_unlocked",
]
