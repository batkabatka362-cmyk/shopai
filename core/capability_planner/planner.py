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

        # 1. Seed discovery -- substring AND match against
        # the registry's LLM-readable fields.
        seeds = self._registry.find(query=goal_text)

        # 1b. Boost: merge in capabilities from peer-store
        # plans that SUCCEEDED for similar goals (loose
        # substring match either direction). Bounded: only
        # fires when >=2 past successes exist + boost
        # candidates max out at 5 entries to prevent
        # over-broadening the seed set. Conservative on
        # purpose -- substring-matched seeds always come
        # first; peer-success boost capabilities are
        # appended only when registry-resolvable + not
        # already present.
        boost_caps, boost_meta = self._peer_success_boost(
            goal_text,
        )
        seed_names_seen = {c.name for c in seeds}
        for cap in boost_caps:
            if cap.name in seed_names_seen:
                continue
            seeds.append(cap)
            seed_names_seen.add(cap.name)

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
        if boost_meta and boost_meta.get("added"):
            plan.notes.append(
                f"Boosted {len(boost_meta['added'])} "
                f"capability/-ies from peer-store success "
                f"(goal: '{boost_meta['source_goal']}', "
                f"{boost_meta['success_count']}x across "
                f"{boost_meta['n_stores']} store(s)): "
                f"{', '.join(boost_meta['added'])}"
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
            suggested_args=dict(cap.example_input),
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

    def _peer_success_boost(
        self, goal_text: str,
    ) -> tuple[list[Capability], dict[str, Any]]:
        """Look up peer-store successful plans for a goal
        similar to ``goal_text``. Returns (boost_caps,
        meta).

        Conservative selection rules:
          - Sample-size cutoff: only boost when at least
            2 peer-store successes exist for the matched
            goal (sparse data is unreliable signal).
          - Max 5 boost capabilities per call to prevent
            over-broadening.
          - Cycle protection: capability name MUST resolve
            in the registry (hallucinated names dropped).
          - Best-effort: any import / lookup error returns
            empty result without raising.

        ``meta`` is a small dict the caller can use to
        compose a plan.notes line:
        ``{source_goal, success_count, n_stores, added}``.
        Empty when no boost fired.
        """
        boost_caps: list[Capability] = []
        meta: dict[str, Any] = {}
        if not goal_text:
            return boost_caps, meta
        try:
            from .plan_history import successful_plans
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_peer_success_boost: import raised: %s",
                exc,
            )
            return boost_caps, meta
        try:
            rows = successful_plans(
                since_seconds=86400 * 30, top_n=5,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_peer_success_boost: lookup raised: %s",
                exc,
            )
            return boost_caps, meta
        if not rows:
            return boost_caps, meta

        # Find the best matching past plan by loose
        # substring similarity. Pick the row with the
        # highest success_count whose goal phrase overlaps
        # the current goal in either direction.
        goal_l = goal_text.lower()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            past_goal = (r.get("goal") or "").lower()
            if not past_goal:
                continue
            if (
                past_goal in goal_l
                or goal_l in past_goal
            ):
                candidates.append(r)
        if not candidates:
            return boost_caps, meta

        # Pick the highest-success match (ties broken by
        # ``successful_plans`` ordering).
        candidates.sort(
            key=lambda r: -int(
                r.get("success_count", 0) or 0,
            ),
        )
        best = candidates[0]
        if int(best.get("success_count", 0) or 0) < 2:
            return boost_caps, meta

        # Resolve capability names against the registry.
        added: list[str] = []
        for name in (best.get("capabilities") or [])[:5]:
            cap = self._registry.get(name)
            if cap is None:
                continue
            boost_caps.append(cap)
            added.append(name)

        meta = {
            "source_goal": best.get("goal", ""),
            "success_count": int(
                best.get("success_count", 0) or 0,
            ),
            "n_stores": len(best.get("stores") or []),
            "added": added,
        }
        return boost_caps, meta

    def _add_cross_store_advisory(self, plan: Plan) -> None:
        """Surface peer-store success signal for the plan's
        goal. When ``successful_plans`` returns rows for a
        similar goal, add a plan.notes line so operators see
        "this goal has worked elsewhere with these
        capabilities".

        Read-only advisory -- doesn't change the plan's
        steps (the deterministic walker has already
        decided them). Future PR can promote this from
        advisory to actually boosting the seed set.
        """
        goal = (plan.goal or "").strip()
        if not goal:
            return
        try:
            from .plan_history import successful_plans
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_add_cross_store_advisory: import "
                "raised: %s", exc,
            )
            return
        try:
            # Look back further than the planner's
            # default decoration (30d) -- recommendations
            # surface even older successes if relevant.
            rows = successful_plans(
                since_seconds=86400 * 30,
                top_n=3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_add_cross_store_advisory: lookup "
                "raised: %s", exc,
            )
            return

        # Filter to peer-store successes whose goal phrase
        # overlaps the current goal (loose substring match).
        goal_l = goal.lower()
        matches = []
        for r in rows:
            past_goal = (r.get("goal") or "").lower()
            if not past_goal:
                continue
            # Match either direction: past goal contained
            # in current OR current contained in past.
            if (
                past_goal in goal_l
                or goal_l in past_goal
            ):
                matches.append(r)
        if not matches:
            return

        # Compose a single advisory line summarising the
        # cross-store signal.
        first = matches[0]
        n_stores = len(first.get("stores") or [])
        plan.notes.append(
            f"Cross-store signal: '{first['goal']}' has "
            f"succeeded {first['success_count']}x across "
            f"{n_stores} peer store(s) with capabilities: "
            f"{', '.join(first['capabilities'])}"
        )

    def _decorate_with_history(self, plan: Plan) -> None:
        """Populate ``history_sample_size`` +
        ``history_success_rate`` on each step from
        ``plan_history.outcome_breakdown``. Best-effort:
        missing / failing history is silently skipped.

        Sample size cutoff: when fewer than 1 prior
        executed invocation exists for a capability, the
        success_rate stays at 0.0. Operators see the small
        sample via history_sample_size = 0/1/2 etc.
        """
        try:
            from .plan_history import outcome_breakdown
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_decorate_with_history: import raised: %s",
                exc,
            )
            return
        for step in plan.steps:
            try:
                b = outcome_breakdown(
                    capability=step.capability_name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "_decorate_with_history: lookup "
                    "raised for %s: %s",
                    step.capability_name, exc,
                )
                continue
            step.history_sample_size = int(
                b.get("executed_total", 0)
            )
            step.history_success_rate = float(
                b.get("success_rate", 0.0)
            )

    def _finalise(self, plan: Plan) -> None:
        """Compute audit_coverage + cli_sequence + piping
        wire-up from the plan's step list.

        ``cli_sequence`` deduplicates: an orchestrator
        CLI claims the steps it covers, so per-step CLIs
        whose capabilities are in the orchestrator's
        composes_with are dropped.

        Composition piping: when step N declares
        ``composes_input`` in its registry record AND step
        N-1 (or earlier) is in its ``composes_with`` set,
        set ``step.pipe_from = prior_name`` and
        ``step.pipe_as = composes_input``. The multi-step
        executor reads these at runtime and pipes the
        prior step's result.data into step N's kwargs.
        """
        coverage: list[str] = []
        for s in plan.steps:
            for k in s.closes_audits:
                if k not in coverage:
                    coverage.append(k)
        plan.audit_coverage = coverage

        # Composition piping wire-up. Scan each step
        # against EARLIER steps; pipe from the latest peer
        # that matches.
        for idx, step in enumerate(plan.steps):
            cap = self._registry.get(step.capability_name)
            if cap is None or not cap.composes_input:
                continue
            # Find an earlier step that is in this
            # capability's composes_with set.
            for prior in reversed(plan.steps[:idx]):
                if (
                    prior.capability_name
                    in cap.composes_with
                ):
                    step.pipe_from = prior.capability_name
                    step.pipe_as = cap.composes_input
                    break

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

        # Best-effort: decorate steps with historical
        # success rates from plan_history. Missing /
        # erroring history is silently skipped so the
        # planner stays usable when the history file is
        # empty / corrupt / hidden by the test-env guard.
        self._decorate_with_history(plan)
        # Best-effort: append a cross-store advisory note
        # when peer stores have succeeded with similar
        # goals. Read-only advisory; planner steps
        # unchanged.
        self._add_cross_store_advisory(plan)


# ── Module-level convenience wrappers ─────────────────────


def plan_for_goal(goal: str) -> Plan:
    """Module-level shortcut for ``Planner().plan_for_goal(goal)``.
    """
    return Planner().plan_for_goal(goal)


def plan_for_audit_gaps(failing_keys: Iterable[str]) -> Plan:
    """Module-level shortcut for
    ``Planner().plan_for_audit_gaps(failing_keys)``."""
    return Planner().plan_for_audit_gaps(failing_keys)
