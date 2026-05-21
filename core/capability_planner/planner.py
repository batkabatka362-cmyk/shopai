"""Deterministic substrate planner.

Walks the capability registry to build a Plan for a goal phrase
or a set of failing audit checks. No LLM call -- substring +
composition graph walking only. The LLM-driven planner (future
PR) will replace the substring matcher with semantic retrieval
behind the same ``Planner.plan_for_goal`` call site.

Algorithm overview
------------------

For ``plan_for_goal(goal)``:
  1. ``registry.find(query=goal)`` -> seed capabilities.
  2. For each seed, walk ``composes_with`` to gather chained
     capabilities (e.g. generator -> applier).
  3. Group steps by orchestrator. If any orchestrator's
     ``composes_with`` or ``audit_checks_closed`` covers the
     seeds, prefer the orchestrator CLI over the sub-CLIs.
  4. Append an ``audit_store`` verification step when at
     least one applier/seeder step closes an audit check.
  5. Build a CLI sequence: orchestrators first, then any
     remaining sub-capabilities not covered by an
     orchestrator.

For ``plan_for_audit_gaps(failing_keys)``:
  1. For each failing audit key, ``registry.find(
     closes_audit=key)`` -> writer that closes it.
  2. Walk back via ``composes_with`` to find required
     generator.
  3. Group writers by orchestrator that covers the most gaps
     (prefer ``launch_store`` for multi-gap plans).
  4. Append verification.

Both paths emit the same Plan schema. Empty results are
returned, not exceptions -- the planner is a query layer,
not an oracle.
"""
from __future__ import annotations

import logging
from typing import Iterable

from core.capability_registry import (
    Capability,
    CapabilityKind,
    get_registry,
)
from core.capability_registry.bootstrap import (
    ensure_registered,
)

from .plan import Plan, PlanStep

logger = logging.getLogger(__name__)


# Orchestrators whose output CLI a planner prefers over
# multiple sub-CLIs. Pre-populated; future iterations can
# move this to a registry field if it grows past a handful.
_PREFERRED_ORCHESTRATORS: tuple[str, ...] = (
    "launch_store",
    "post_launch_enrich",
)


class Planner:
    """Deterministic planner. Stateful enough to cache the
    registry handle; the registry itself is the source of
    truth.

    Args:
        skip_bootstrap: When True, the planner does NOT call
            ``ensure_registered()`` on construction. Test
            fixtures that want full isolation (custom
            registrations only, no launch_chain bleed-through)
            pass True after seeding their own capabilities.
            Default False -- CLI / production paths bootstrap.
    """

    def __init__(self, *, skip_bootstrap: bool = False) -> None:
        if not skip_bootstrap:
            ensure_registered()
        self._registry = get_registry()

    # ── Goal-to-plan ──────────────────────────────────────

    def plan_for_goal(self, goal: str) -> Plan:
        """Build a Plan that addresses ``goal``.

        ``goal`` is a free-form phrase like "make store
        launchable", "improve mobile design", "seed
        products". The planner substring-matches it against
        the registry's LLM-readable fields.
        """
        goal_text = (goal or "").strip()
        plan = Plan(goal=goal_text)

        if not goal_text:
            plan.notes.append(
                "Empty goal -- returning empty plan."
            )
            return plan

        # 1. Seed discovery
        seeds = self._registry.find(query=goal_text)
        plan.relevant_capabilities = [c.name for c in seeds]
        if not seeds:
            plan.notes.append(
                f"No registered capabilities match "
                f"'{goal_text}'. Try a broader phrase or "
                f"register more capabilities."
            )
            return plan
        plan.notes.append(
            f"Found {len(seeds)} capability/-ies matching "
            f"'{goal_text}'."
        )

        # 2. Orchestrator shortcut
        orch = self._pick_orchestrator(seeds)
        if orch is not None:
            plan.notes.append(
                f"Orchestrator '{orch.name}' covers the "
                f"matched capabilities; using it instead of "
                f"the per-step CLIs."
            )
            plan.steps.append(
                self._step_for(orch, role="orchestrator"),
            )
            self._append_verification_step(plan, [orch])
            self._finalise(plan)
            return plan

        # 3. Per-seed expansion via composes_with
        seen: set[str] = set()
        for seed in seeds:
            chain = self._walk_chain(seed)
            for cap in chain:
                if cap.name in seen:
                    continue
                seen.add(cap.name)
                plan.steps.append(
                    self._step_for(
                        cap,
                        role=self._infer_role(cap),
                    ),
                )

        # 4. Verification append
        applier_seeds = [
            c for c in seeds
            if c.kind in (
                CapabilityKind.APPLIER,
                CapabilityKind.SEEDER,
            )
        ]
        if applier_seeds or any(
            s.closes_audits for s in plan.steps
        ):
            self._append_verification_step(plan, seeds)

        self._finalise(plan)
        return plan

    # ── Audit-driven ──────────────────────────────────────

    def plan_for_audit_gaps(
        self, failing_keys: Iterable[str],
    ) -> Plan:
        """Build a Plan that closes the listed audit gaps.

        Walks the registry for each failing check, finds the
        writer(s) that close it, and groups by orchestrator
        when one covers multiple gaps in a single CLI call.
        """
        keys = [k for k in (failing_keys or []) if k]
        plan = Plan(goal=f"close audit gaps: {', '.join(keys)}")

        if not keys:
            plan.notes.append("No failing keys supplied.")
            return plan

        # 1. Discover writers per failing key
        writers_by_key: dict[str, list[Capability]] = {}
        for k in keys:
            writers_by_key[k] = self._registry.find(
                closes_audit=k,
            )

        unrecognised = [
            k for k, w in writers_by_key.items() if not w
        ]
        if unrecognised:
            plan.notes.append(
                f"No registered writer closes: "
                f"{', '.join(unrecognised)}. "
                f"These checks are likely operator-driven "
                f"(Shopify admin) -- their fix_hint will "
                f"surface in shopai launch-audit."
            )

        all_writers: list[Capability] = []
        for w_list in writers_by_key.values():
            for w in w_list:
                if w not in all_writers:
                    all_writers.append(w)

        plan.relevant_capabilities = [
            w.name for w in all_writers
        ]
        if not all_writers:
            return plan

        # 2. Orchestrator shortcut -- does an orchestrator
        # close the most gaps in one shot?
        best_orch = self._best_audit_orchestrator(keys)
        if best_orch is not None:
            covered = set(
                best_orch.audit_checks_closed,
            ) & set(keys)
            plan.notes.append(
                f"Orchestrator '{best_orch.name}' closes "
                f"{len(covered)} of {len(keys)} gaps in one "
                f"command. Preferring it."
            )
            plan.steps.append(
                self._step_for(
                    best_orch, role="orchestrator",
                ),
            )
            # If the orchestrator does NOT cover all gaps,
            # add the leftover writers explicitly.
            leftover = set(keys) - covered
            for k in sorted(leftover):
                for w in writers_by_key.get(k, []):
                    if (
                        w.name == best_orch.name
                        or any(
                            s.capability_name == w.name
                            for s in plan.steps
                        )
                    ):
                        continue
                    plan.steps.append(
                        self._step_for(
                            w, role=self._infer_role(w),
                        ),
                    )
            self._append_verification_step(plan, all_writers)
            self._finalise(plan)
            return plan

        # 3. No orchestrator -- emit per-writer steps + their
        # generators
        seen: set[str] = set()
        for w in all_writers:
            for cap in self._walk_chain(w):
                if cap.name in seen:
                    continue
                seen.add(cap.name)
                plan.steps.append(
                    self._step_for(
                        cap, role=self._infer_role(cap),
                    ),
                )

        self._append_verification_step(plan, all_writers)
        self._finalise(plan)
        return plan

    # ── Internals ─────────────────────────────────────────

    def _pick_orchestrator(
        self, seeds: list[Capability],
    ) -> Capability | None:
        """Return an orchestrator whose composes_with covers
        the seeds, or None. Prefers the preferred-list."""
        seed_names = {c.name for c in seeds}
        # Seeds may already include an orchestrator
        seed_orchs = [
            c for c in seeds
            if c.kind == CapabilityKind.ORCHESTRATOR
        ]
        if seed_orchs:
            return seed_orchs[0]
        # Check whether any orchestrator on the preferred
        # list explicitly composes with at least one seed
        for name in _PREFERRED_ORCHESTRATORS:
            cap = self._registry.get(name)
            if cap is None:
                continue
            covered = set(cap.composes_with) & seed_names
            # An orchestrator that composes with at least
            # one matched capability is worth offering as
            # the single-command path.
            if covered:
                return cap
        return None

    def _best_audit_orchestrator(
        self, keys: list[str],
    ) -> Capability | None:
        """Among orchestrators, the one that closes the most
        of the requested gaps. Ties favour ``launch_store``
        (it covers the broadest set of writers)."""
        best: Capability | None = None
        best_count = 0
        for cap in self._registry.find(
            kind=CapabilityKind.ORCHESTRATOR,
        ):
            n = len(
                set(cap.audit_checks_closed) & set(keys)
            )
            if n > best_count:
                best, best_count = cap, n
            elif (
                n == best_count
                and best is not None
                and cap.name == "launch_store"
            ):
                best = cap
        return best if best_count > 0 else None

    # Kinds that semantically appear BEFORE their peer in an
    # execution sequence: a generator builds the spec that an
    # applier writes, an engine produces the recommendation
    # that an applier upserts.
    _UPSTREAM_KINDS: frozenset[str] = frozenset({
        CapabilityKind.GENERATOR,
        CapabilityKind.ENRICHER,
        CapabilityKind.ENGINE,
    })
    # Kinds that semantically appear AFTER their peer: an
    # applier consumes a generator's output; an audit verifies
    # an applier's writes.
    _DOWNSTREAM_KINDS: frozenset[str] = frozenset({
        CapabilityKind.APPLIER,
        CapabilityKind.SEEDER,
        CapabilityKind.AUDIT,
    })

    def _walk_chain(
        self, root: Capability, depth: int = 1,
    ) -> list[Capability]:
        """Depth-limited walk along composes_with.

        Returns capabilities in a sensible execution order:
        direct upstream peers (generators / enrichers /
        engines feeding the root) first, then the root, then
        direct downstream peers (appliers / seeders /
        audits consuming the root).

        Default depth=1: only DIRECT neighbors. The
        composition graph is densely connected via
        ``composes_with`` (engines reference engines), and
        transitive expansion would surface the whole graph
        from any seed. Direct-only keeps each seed's chain
        focused on its immediate execution context.

        Symmetric: walks composes_with bidirectionally,
        relying on each peer's ``kind`` to decide upstream
        vs downstream position.

        Depth cap is paranoid -- the registry is a DAG
        today, but a cycle would otherwise infinite-loop.
        """
        order: list[Capability] = []
        visited: set[str] = set()

        def visit(name: str, d: int) -> None:
            if d < 0 or name in visited:
                return
            visited.add(name)
            cap = self._registry.get(name)
            if cap is None:
                return
            # Upstream first
            for peer in cap.composes_with:
                if peer in visited:
                    continue
                peer_cap = self._registry.get(peer)
                if peer_cap is None:
                    continue
                if peer_cap.kind in self._UPSTREAM_KINDS:
                    visit(peer, d - 1)
            if cap not in order:
                order.append(cap)
            # Downstream after
            for peer in cap.composes_with:
                if peer in visited:
                    continue
                peer_cap = self._registry.get(peer)
                if peer_cap is None:
                    continue
                if peer_cap.kind in self._DOWNSTREAM_KINDS:
                    visit(peer, d - 1)

        visit(root.name, depth)
        return order

    def _infer_role(self, cap: Capability) -> str:
        """Map CapabilityKind to a PlanStep.role string."""
        mapping = {
            CapabilityKind.ORCHESTRATOR: "orchestrator",
            CapabilityKind.APPLIER: "applier",
            CapabilityKind.SEEDER: "applier",
            CapabilityKind.GENERATOR: "generator",
            CapabilityKind.ENRICHER: "enricher",
            CapabilityKind.AUDIT: "verification",
            CapabilityKind.ENGINE: "engine",
            CapabilityKind.HYDRATOR: "hydrator",
            CapabilityKind.ADAPTER: "adapter",
        }
        return mapping.get(cap.kind, cap.kind)

    def _step_for(
        self, cap: Capability, *, role: str,
    ) -> PlanStep:
        cli = cap.cli_commands[0] if cap.cli_commands else ""
        return PlanStep(
            capability_name=cap.name,
            role=role,
            description=cap.description,
            cli_command=cli,
            closes_audits=list(cap.audit_checks_closed),
            composes_with_next=list(cap.composes_with),
        )

    def _append_verification_step(
        self, plan: Plan, related: list[Capability],
    ) -> None:
        """Append audit_store verification when the plan
        includes any writer / orchestrator. Avoids appending
        twice."""
        if any(
            s.capability_name == "audit_store"
            for s in plan.steps
        ):
            return
        # Only verify when the plan has at least one write
        # step
        if not any(
            s.role in ("applier", "orchestrator", "enricher")
            for s in plan.steps
        ):
            return
        audit = self._registry.get("audit_store")
        if audit is None:
            return
        plan.steps.append(
            self._step_for(audit, role="verification"),
        )
        plan.notes.append(
            "Appended audit_store verification step so the "
            "plan's outcome is checkable."
        )

    def _finalise(self, plan: Plan) -> None:
        """Compute audit_coverage + cli_sequence from steps.

        ``cli_sequence`` deduplicates: an orchestrator
        CLI claims the steps it covers, so per-step CLIs
        whose capabilities are in the orchestrator's
        composes_with are dropped.
        """
        coverage: list[str] = []
        for s in plan.steps:
            for k in s.closes_audits:
                if k not in coverage:
                    coverage.append(k)
        plan.audit_coverage = coverage

        # Build CLI sequence with orchestrator dedup
        cmds: list[str] = []
        claimed_by_orch: set[str] = set()
        for s in plan.steps:
            if s.role == "orchestrator":
                cap = self._registry.get(s.capability_name)
                if cap is not None:
                    claimed_by_orch.update(cap.composes_with)
        for s in plan.steps:
            if (
                s.role != "orchestrator"
                and s.capability_name in claimed_by_orch
            ):
                continue
            if not s.cli_command:
                continue
            if s.cli_command in cmds:
                continue
            cmds.append(s.cli_command)
        plan.cli_sequence = cmds


# ── Module-level convenience wrappers ─────────────────────


def plan_for_goal(goal: str) -> Plan:
    """Module-level shortcut for ``Planner().plan_for_goal(goal)``.
    """
    return Planner().plan_for_goal(goal)


def plan_for_audit_gaps(failing_keys: Iterable[str]) -> Plan:
    """Module-level shortcut for
    ``Planner().plan_for_audit_gaps(failing_keys)``."""
    return Planner().plan_for_audit_gaps(failing_keys)
