"""Capability registry -- machine-readable catalog of what
ShopAI's substrate can do.

Why this exists
---------------
ShopAI has ~50 engines, ~130 Shopify adapters, and dozens of
appliers, seeders, generators, and writers. Today the only way
to discover "what capability fits this goal?" is by grepping
filenames -- a heuristic that worked at 10 capabilities but
breaks down at 200.

The North Star (see ``project_north_star_shopai_empire.md``)
needs **AI to USE the substrate**, not just operators. For
that to work, the substrate has to be **introspectable**:
every engine + adapter + writer declares what it does in a
shared schema, and a registry surfaces that schema to anyone
who needs it -- the autonomous loop, the LLM planner (Phase 9
upgrade), and Claude during a task.

Three usage patterns
--------------------

1. **Discovery** -- "what writes a discount code?":

       from core.capability_registry import get_registry
       caps = get_registry().find(query="discount")

2. **Goal-to-plan** (planner, future):

       caps = registry.find(closes_audit="active_products")
       # -> [product_seeder, ...]

3. **Verification** -- "what audits does running this close?":

       cap = registry.get("launch_orchestrator")
       cap.audit_checks_closed  # -> ["legal_policies", ...]

The schema is intentionally **growable**: new optional fields
can be added without breaking existing registrations.
Registration is **idempotent** -- importing a module twice
overwrites cleanly. Find/query uses simple substring matching
for now; embeddings can swap in later without changing the
contract.

Design tenets
-------------

- **Explicit registration**, not auto-discovery. Each engine /
  applier / writer registers itself on import. Manual is more
  traceable than file-scanning at this scale.
- **Optional fields default**. A capability with just
  ``name`` + ``kind`` + ``description`` + ``when_to_use`` is
  valid. Richer registrations (inputs, outputs, scopes,
  audits_closed, example_input) earn more leverage but aren't
  required.
- **Test-environment friendly**. The registry is a module-
  level singleton; tests can call ``get_registry().clear()``
  in fixtures.
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    get_registry,
    register_capability,
)

__all__ = [
    "Capability",
    "CapabilityKind",
    "get_registry",
    "register_capability",
]
