"""AGI Orphan Investigator — W963-78 (operator drill).

When W963-47 reconcile_fleet surfaces orphan actions
(revenue-driving actions that matched no orders within the
attribution window), the operator wants to know:

  1. WHICH engines are producing the most orphans?
  2. IS this clustered in time (one bad batch) or spread?
  3. ARE specific engines reliably orphaned vs occasional?
  4. WHAT should the operator do (suppress engine? widen
     attribution window? check upstream code path?)

This engine consumes reconcile_fleet output, aggregates the
orphan list across stores, and emits structured drill
guidance.

Pattern J + Pattern Q.

CLI:
  shopai investigate-orphans [--days N] [--json]
"""
from .flow import AgiOrphanInvestigatorEngine

__all__ = ["AgiOrphanInvestigatorEngine"]
