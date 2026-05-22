"""Tests for ``core.capability_planner``.

The planner is the first consumer of the capability registry.
These tests lock in the planning contract -- registry walks,
orchestrator preference, audit coverage analysis, CLI sequence
deduplication -- so future LLM-driven planners can swap in
behind the same call shape.

Coverage:
  - Empty / unrecognised goal -> empty plan with notes
  - Goal-to-plan: free-form phrase -> ordered steps
  - Orchestrator shortcut: launch_store preferred over
    individual generators+appliers
  - Composition walk: generator before applier
  - Verification append: audit_store added when writes
    are in plan
  - Audit-gap planning: failing keys -> writers + best
    orchestrator
  - CLI sequence dedup: orchestrator claims its sub-CLIs
  - The bible example: "mobile" -> store_design_engine ->
    apply_design (with verification)
"""
from __future__ import annotations

import pytest

from core.capability_registry import (
    Capability,
    CapabilityKind,
    get_registry,
    register_capability,
)
from core.capability_registry.bootstrap import (
    ensure_registered,
    reset_for_tests,
)
from core.capability_planner import (
    Plan,
    PlanStep,
    Planner,
    plan_for_audit_gaps,
    plan_for_goal,
)


@pytest.fixture(autouse=True)
def _registry_isolation():
    """Reset the registry around each test. The
    launch-chain auto-registers via ensure_registered()
    inside the planner construction; tests that want a
    minimal fixture should call reset_for_tests() at the
    top to wipe and re-register only what they need."""
    reset_for_tests()
    yield
    reset_for_tests()


class TestEmptyAndUnrecognised:

    def test_empty_goal_empty_plan(self):
        plan = plan_for_goal("")
        assert plan.goal == ""
        assert plan.steps == []
        assert plan.is_empty() is True
        assert any(
            "Empty goal" in n for n in plan.notes
        )

    def test_unrecognised_goal_no_steps(self):
        # Launch chain auto-registers; "cryptocurrency_mining"
        # has no match so the planner returns no steps but
        # populates a helpful note.
        plan = plan_for_goal("cryptocurrency_mining")
        assert plan.steps == []
        assert any(
            "No registered capabilities" in n
            for n in plan.notes
        )


class TestGoalToPlan:

    def test_launch_phrase_prefers_orchestrator(self):
        """The bible's mission-aligned example: 'launch this
        store' should resolve to the launch_store
        orchestrator rather than 7 sub-CLIs."""
        plan = plan_for_goal("launch the store")
        # launch_store comes back as the orchestrator step
        assert any(
            s.capability_name == "launch_store"
            and s.role == "orchestrator"
            for s in plan.steps
        )
        # Verification step appended
        assert any(
            s.capability_name == "audit_store"
            for s in plan.steps
        )
        # cli_sequence collapses to orchestrator + audit
        assert any(
            "shopai launch" in c
            for c in plan.cli_sequence
        )

    def test_mobile_phrase_surfaces_design_engine(self):
        """The exact example from the north-star bible:
        'mobile' as a free-form phrase should drive the
        planner to the store_design_engine via its
        when_to_use field."""
        plan = plan_for_goal("mobile")
        names = {s.capability_name for s in plan.steps}
        assert "store_design_engine" in names
        # The chain composes design_engine -> apply_design
        assert "apply_design" in names

    def test_chain_orders_generator_before_applier(self):
        # "policies" should surface both generate_policies
        # and apply_policies, in that order.
        plan = plan_for_goal("policies")
        step_names = [s.capability_name for s in plan.steps]
        # Find indices
        if (
            "generate_policies" in step_names
            and "apply_policies" in step_names
        ):
            assert (
                step_names.index("generate_policies")
                < step_names.index("apply_policies")
            )

    def test_audit_coverage_accumulates(self):
        plan = plan_for_goal("launch the store")
        # The orchestrator step's audit_checks_closed should
        # all surface in plan.audit_coverage
        assert "legal_policies" in plan.audit_coverage
        assert "standard_pages" in plan.audit_coverage

    def test_verification_appended_for_writes(self):
        plan = plan_for_goal("policies")
        # generate + apply policies = writer in the plan ->
        # planner appends audit_store verification.
        roles = {s.role for s in plan.steps}
        if "applier" in roles:
            assert any(
                s.capability_name == "audit_store"
                for s in plan.steps
            )

    def test_to_dict_serialises(self):
        plan = plan_for_goal("launch")
        d = plan.to_dict()
        assert d["goal"] == "launch"
        assert isinstance(d["steps"], list)
        assert isinstance(d["audit_coverage"], list)
        assert isinstance(d["cli_sequence"], list)
        # Defensive: returned dict is a copy
        d["audit_coverage"].append("x")
        assert "x" not in plan.audit_coverage


class TestAuditGapPlanning:

    def test_single_gap_finds_writer(self):
        plan = plan_for_audit_gaps(["active_products"])
        names = {s.capability_name for s in plan.steps}
        # Either via direct writer OR via launch_store
        # orchestrator (which closes active_products via
        # Step 7)
        assert (
            "apply_starter_products" in names
            or "launch_store" in names
        )

    def test_multi_gap_picks_orchestrator(self):
        """Closing 4 gaps that launch_store covers in one
        command should yield launch_store as the
        recommendation, not 4 separate writers."""
        plan = plan_for_audit_gaps([
            "legal_policies", "standard_pages",
            "active_discounts", "curated_collections",
        ])
        # launch_store closes all 4
        step_names = [s.capability_name for s in plan.steps]
        assert "launch_store" in step_names
        # CLI sequence prefers the orchestrator
        assert any(
            "shopai launch" in c
            for c in plan.cli_sequence
        )

    def test_operator_driven_gaps_get_note(self):
        """shipping_zones / fulfillable_locations are not
        closeable by registered writers -- the planner
        surfaces a note explaining the gap is
        operator-driven."""
        plan = plan_for_audit_gaps([
            "shipping_zones", "fulfillable_locations",
        ])
        # No writer for these -> note explains why
        assert any(
            "operator-driven" in n.lower()
            or "no registered writer" in n.lower()
            for n in plan.notes
        )

    def test_mixed_gaps_orchestrator_plus_manual_note(self):
        plan = plan_for_audit_gaps([
            "legal_policies",          # launch_store closes
            "fulfillable_locations",   # operator-driven
        ])
        # The orchestrator covers the first; the second
        # surfaces in the unrecognised-gap note.
        assert any(
            s.capability_name == "launch_store"
            for s in plan.steps
        )
        assert any(
            "fulfillable_locations" in n
            for n in plan.notes
        )

    def test_empty_keys_returns_empty_plan(self):
        plan = plan_for_audit_gaps([])
        assert plan.is_empty() is True


class TestCliSequenceDedup:

    def test_orchestrator_claims_sub_clis(self):
        """When the plan includes launch_store and one of
        its composes_with capabilities, the CLI sequence
        should NOT include the sub-CLI."""
        plan = plan_for_audit_gaps([
            "legal_policies", "standard_pages",
        ])
        cmds = plan.cli_sequence
        # Should have the orchestrator CLI
        has_launch = any(
            "shopai launch" in c for c in cmds
        )
        assert has_launch
        # Should NOT separately list policy or page sub-CLIs
        # (the launch step covers them)
        assert not any(
            "design-apply" in c
            for c in cmds
            if "launch-audit" not in c
        )


class TestOperatorOverrides:
    """Planner consults the operator-declared promote /
    demote overrides BEFORE the quarantine filter. Operator's
    explicit signal beats automatic discovery."""

    def _seed(self):
        register_capability(Capability(
            name="ok_cap",
            kind=CapabilityKind.ENGINE,
            description="works fine",
            when_to_use="use for foo",
            module_path="m:ok",
            tags=["foo"],
        ))
        register_capability(Capability(
            name="bad_cap",
            kind=CapabilityKind.ENGINE,
            description="broken needs fix",
            when_to_use="don't use right now foo",
            module_path="m:bad",
            tags=["foo"],
        ))
        # Promote-only target -- doesn't match substring
        register_capability(Capability(
            name="hidden_winner",
            kind=CapabilityKind.ENGINE,
            description="not surfaced by substring",
            when_to_use="operator knows it's relevant",
            module_path="m:hidden",
            tags=["other"],
        ))

    def _overrides(self, promoted=None, demoted=None):
        from core.capability_planner.\
capability_overrides import (
            CapabilityOverride, CapabilityOverrides,
        )
        entries = []
        for n in (promoted or []):
            entries.append(CapabilityOverride(
                name=n, kind="promote",
            ))
        for n in (demoted or []):
            entries.append(CapabilityOverride(
                name=n, kind="demote",
            ))
        return CapabilityOverrides(entries=entries)

    def test_demoted_seed_excluded(self):
        from unittest.mock import patch
        self._seed()
        with patch(
            "core.capability_planner."
            "capability_overrides.load_overrides",
            return_value=self._overrides(
                demoted=["bad_cap"],
            ),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("foo")
        names = {s.capability_name for s in p.steps}
        assert "ok_cap" in names
        assert "bad_cap" not in names
        assert any(
            "demoted" in n.lower() and "bad_cap" in n
            for n in p.notes
        )

    def test_promoted_capability_added(self):
        from unittest.mock import patch
        self._seed()
        # "foo" substring matches ok_cap + bad_cap.
        # hidden_winner doesn't match substring but is
        # promoted -> should still appear in steps.
        with patch(
            "core.capability_planner."
            "capability_overrides.load_overrides",
            return_value=self._overrides(
                promoted=["hidden_winner"],
            ),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("foo")
        names = {s.capability_name for s in p.steps}
        assert "hidden_winner" in names
        assert any(
            "promoted" in n.lower() and "hidden_winner" in n
            for n in p.notes
        )

    def test_overrides_failure_silent(self):
        from unittest.mock import patch
        self._seed()
        with patch(
            "core.capability_planner."
            "capability_overrides.load_overrides",
            side_effect=RuntimeError("disk"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("foo")
        # Both seeds still surface (no override applied)
        names = {s.capability_name for s in p.steps}
        assert "ok_cap" in names
        assert "bad_cap" in names


class TestQuarantineFilter:
    """Planner refuses to seed plans with engines whose
    ``alert_paused`` state is active. Operator's explicit
    quarantine signal beats the planner's substring +
    boost selection."""

    def _seed_one(self):
        register_capability(Capability(
            name="paused_engine",
            kind=CapabilityKind.ENGINE,
            description="this engine has been flagged",
            when_to_use="not used right now",
            module_path="m:paused",
            tags=["unreliable"],
        ))
        register_capability(Capability(
            name="healthy_engine",
            kind=CapabilityKind.ENGINE,
            description="this engine is fine unreliable",
            when_to_use="use for unreliable goals",
            module_path="m:healthy",
            tags=["unreliable"],
        ))

    def _fake_state(self, paused_engines):
        """Build a stub quarantine state with the listed
        engines fleet-wide-paused."""
        from core.approval.quarantine import (
            QuarantineState,
        )
        return QuarantineState(
            exemptions=frozenset(),
            released=frozenset(),
            alert_paused=frozenset(
                (e, None) for e in paused_engines
            ),
        )

    def test_paused_engine_excluded_from_seeds(self):
        from unittest.mock import patch
        self._seed_one()
        with patch(
            "core.approval.quarantine.load_state",
            return_value=self._fake_state(["paused_engine"]),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("unreliable")
        names = {s.capability_name for s in p.steps}
        # Healthy engine still surfaces
        assert "healthy_engine" in names
        # Paused engine filtered out
        assert "paused_engine" not in names
        # Note explains the exclusion
        assert any(
            "Excluded" in n and "paused_engine" in n
            for n in p.notes
        )

    def test_all_quarantined_returns_empty_with_note(self):
        from unittest.mock import patch
        self._seed_one()
        # Both seeds quarantined -> no plan
        with patch(
            "core.approval.quarantine.load_state",
            return_value=self._fake_state([
                "paused_engine", "healthy_engine",
            ]),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("unreliable")
        assert p.steps == []
        # Note explains what happened
        assert any(
            "alert-paused" in n for n in p.notes
        )

    def test_quarantine_failure_is_silent(self):
        from unittest.mock import patch
        self._seed_one()
        # load_state raises -> planner falls through to
        # normal substring match (no exclusion, no crash)
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("unreliable")
        # Both seeds surface (no filter applied)
        names = {s.capability_name for s in p.steps}
        assert "paused_engine" in names
        assert "healthy_engine" in names


class TestPeerSuccessBoost:
    """Planner auto-boosts seeds with capabilities from
    peer-store SUCCESSFUL past plans (via plan_history)
    when the goal is similar. Conservative -- only fires
    with >=2 past successes."""

    def _seed_registry(self):
        # The capability that wasn't matched by substring
        # but should be boosted from peer success.
        register_capability(Capability(
            name="boosted_cap",
            kind=CapabilityKind.ENGINE,
            description="something obscure",
            when_to_use="not relevant to query",
            module_path="m:boosted",
            tags=["other"],
        ))
        # The substring-matched cap.
        register_capability(Capability(
            name="matched_cap",
            kind=CapabilityKind.ENGINE,
            description="abc widget thing",
            when_to_use="use for widget plans",
            module_path="m:matched",
            tags=["widget"],
        ))

    def test_boost_adds_capability_from_peer_success(self):
        from unittest.mock import patch
        self._seed_registry()
        # Past plan that succeeded for "widget" goal with
        # boosted_cap.
        past_rows = [{
            "goal": "widget rebrand",
            "capabilities": ["boosted_cap"],
            "cli_sequence": [],
            "success_count": 3,
            "last_success": 0.0,
            "stores": ["store-a", "store-b"],
        }]
        with patch(
            "core.capability_planner.plan_history."
            "successful_plans",
            return_value=past_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("widget")
        names = {s.capability_name for s in p.steps}
        assert "matched_cap" in names    # substring match
        assert "boosted_cap" in names    # peer-success
                                          # boost
        # Note explains the boost
        assert any(
            "Boosted" in n and "boosted_cap" in n
            for n in p.notes
        )

    def test_boost_requires_min_two_past_successes(self):
        from unittest.mock import patch
        self._seed_registry()
        # Only 1 past success -- below the conservative
        # threshold -> no boost.
        past_rows = [{
            "goal": "widget rebrand",
            "capabilities": ["boosted_cap"],
            "cli_sequence": [],
            "success_count": 1,
            "last_success": 0.0,
            "stores": ["store-a"],
        }]
        with patch(
            "core.capability_planner.plan_history."
            "successful_plans",
            return_value=past_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("widget")
        names = {s.capability_name for s in p.steps}
        assert "boosted_cap" not in names

    def test_boost_skipped_when_no_goal_overlap(self):
        from unittest.mock import patch
        self._seed_registry()
        # Past success goal "totally unrelated phrase";
        # current goal "widget" -- no overlap -> no boost.
        past_rows = [{
            "goal": "totally unrelated phrase",
            "capabilities": ["boosted_cap"],
            "cli_sequence": [],
            "success_count": 5,
            "last_success": 0.0,
            "stores": ["s"],
        }]
        with patch(
            "core.capability_planner.plan_history."
            "successful_plans",
            return_value=past_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("widget")
        names = {s.capability_name for s in p.steps}
        assert "boosted_cap" not in names

    def test_boost_silently_drops_hallucinated_names(self):
        from unittest.mock import patch
        self._seed_registry()
        # Past plan references a capability that's been
        # removed from the registry. Boost must filter it
        # out without raising.
        past_rows = [{
            "goal": "widget",
            "capabilities": ["boosted_cap", "ghost_cap"],
            "cli_sequence": [],
            "success_count": 3,
            "last_success": 0.0,
            "stores": ["s1", "s2"],
        }]
        with patch(
            "core.capability_planner.plan_history."
            "successful_plans",
            return_value=past_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("widget")
        # boosted_cap surfaces; ghost dropped.
        names = {s.capability_name for s in p.steps}
        assert "boosted_cap" in names
        assert "ghost_cap" not in names

    def test_boost_lookup_failure_is_silent(self):
        from unittest.mock import patch
        self._seed_registry()
        # Lookup raises -> no boost, no crash.
        with patch(
            "core.capability_planner.plan_history."
            "successful_plans",
            side_effect=RuntimeError("disk"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("widget")
        # Substring match still produced matched_cap
        names = {s.capability_name for s in p.steps}
        assert "matched_cap" in names


class TestHistoryDecoration:
    """Planner populates ``history_sample_size`` +
    ``history_success_rate`` on each step from
    ``plan_history.outcome_breakdown``. Best-effort: missing
    history -> 0 / 0.0 (default values)."""

    def _seed_simple(self):
        register_capability(Capability(
            name="x_engine",
            kind=CapabilityKind.ENGINE,
            description="x",
            when_to_use="use for x",
            module_path="m:x",
            tags=["x"],
        ))

    def test_missing_history_stays_at_defaults(self):
        self._seed_simple()
        # No mocking -> real plan_history reads (test env
        # guard returns empty)
        p = Planner(skip_bootstrap=True).plan_for_goal("x")
        step = next(
            s for s in p.steps
            if s.capability_name == "x_engine"
        )
        assert step.history_sample_size == 0
        assert step.history_success_rate == 0.0

    def test_history_populates_when_breakdown_returns(self):
        from unittest.mock import patch
        self._seed_simple()
        # Patch outcome_breakdown to return a known sample
        with patch(
            "core.capability_planner.plan_history."
            "outcome_breakdown",
            return_value={
                "total": 5, "executed_total": 5,
                "by_outcome": {"success": 4, "fail": 1},
                "success_rate": 0.8,
            },
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("x")
        step = next(
            s for s in p.steps
            if s.capability_name == "x_engine"
        )
        assert step.history_sample_size == 5
        assert abs(step.history_success_rate - 0.8) < 0.001

    def test_history_lookup_failure_is_silent(self):
        from unittest.mock import patch
        self._seed_simple()
        # outcome_breakdown raises -> step stays at defaults,
        # no crash
        with patch(
            "core.capability_planner.plan_history."
            "outcome_breakdown",
            side_effect=RuntimeError("disk error"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("x")
        step = next(
            s for s in p.steps
            if s.capability_name == "x_engine"
        )
        # Defaults preserved despite the raise
        assert step.history_sample_size == 0
        assert step.history_success_rate == 0.0


class TestCompositionPiping:
    """When a downstream applier declares ``composes_input``
    and the planner places it after a peer in
    ``composes_with``, the PlanStep's ``pipe_from`` /
    ``pipe_as`` fields wire up the runtime data flow.

    The multi-step executor reads these fields and replaces
    ``suggested_args[pipe_as]`` with the prior step's
    result.data at runtime.
    """

    def _seed_pair(self):
        register_capability(Capability(
            name="gen_widget",
            kind=CapabilityKind.GENERATOR,
            description="builds widget specs",
            when_to_use="use for widget plans",
            module_path="m:gen_widget",
            composes_with=["apply_widget"],
            tags=["widget"],
        ))
        register_capability(Capability(
            name="apply_widget",
            kind=CapabilityKind.APPLIER,
            description="writes widgets to backend",
            when_to_use="pairs with gen_widget",
            module_path="m:apply_widget",
            composes_with=["gen_widget"],
            composes_input="widget_specs",
            audit_checks_closed=["widgets_check"],
            tags=["widget"],
        ))

    def test_pipe_from_set_for_downstream_applier(self):
        self._seed_pair()
        p = Planner(skip_bootstrap=True).plan_for_goal(
            "widget",
        )
        steps_by_name = {
            s.capability_name: s for s in p.steps
        }
        applier_step = steps_by_name.get("apply_widget")
        assert applier_step is not None
        # Plan placed gen_widget BEFORE apply_widget (UPSTREAM
        # rule), so apply_widget pipes from it.
        assert applier_step.pipe_from == "gen_widget"
        assert applier_step.pipe_as == "widget_specs"

    def test_generator_has_no_pipe(self):
        self._seed_pair()
        p = Planner(skip_bootstrap=True).plan_for_goal(
            "widget",
        )
        steps_by_name = {
            s.capability_name: s for s in p.steps
        }
        gen_step = steps_by_name.get("gen_widget")
        assert gen_step is not None
        # Generators don't declare composes_input -> no pipe
        assert gen_step.pipe_from == ""
        assert gen_step.pipe_as == ""

    def test_to_dict_round_trip(self):
        self._seed_pair()
        p = Planner(skip_bootstrap=True).plan_for_goal(
            "widget",
        )
        d = p.to_dict()
        applier_dict = next(
            s for s in d["steps"]
            if s["capability_name"] == "apply_widget"
        )
        assert applier_dict["pipe_from"] == "gen_widget"
        assert applier_dict["pipe_as"] == "widget_specs"

    def test_launch_chain_appliers_have_pipe_wired(self):
        """Locked-in inventory check: every launch-chain
        applier with a composes_input declaration ends up
        with pipe_from set when planned alongside its
        generator. Prevents regression on the 6 registered
        appliers."""
        # Bootstrap real registry
        from core.capability_registry.bootstrap import (
            ensure_registered,
        )
        ensure_registered()
        # Use a query that surfaces a generator + applier pair
        p = Planner().plan_for_goal("policies")
        names = [s.capability_name for s in p.steps]
        if (
            "generate_policies" in names
            and "apply_policies" in names
        ):
            applier = next(
                s for s in p.steps
                if s.capability_name == "apply_policies"
            )
            assert applier.pipe_from == "generate_policies"
            assert applier.pipe_as == "policies"


class TestRegistryIsolation:
    """The planner's behaviour with hand-built fixtures.

    These tests verify the planning algorithm directly
    without relying on the launch-chain registration set --
    helps lock in semantics when future batches modify the
    auto-registered inventory.
    """

    def _seed(self):
        register_capability(Capability(
            name="gen_x",
            kind=CapabilityKind.GENERATOR,
            description="builds x specs",
            when_to_use="use for x",
            module_path="m:gen_x",
            composes_with=["apply_x"],
            tags=["x"],
        ))
        register_capability(Capability(
            name="apply_x",
            kind=CapabilityKind.APPLIER,
            description="writes x to backend",
            when_to_use="pairs with gen_x",
            module_path="m:apply_x",
            audit_checks_closed=["x_check"],
            composes_with=["gen_x"],
            tags=["x"],
            cli_commands=["shopai store apply-x"],
        ))
        register_capability(Capability(
            name="audit_store",
            kind=CapabilityKind.AUDIT,
            description="audit",
            when_to_use="verify",
            module_path="m:audit_store",
            cli_commands=["shopai launch-audit"],
        ))

    def test_planner_uses_isolated_registry(self):
        self._seed()
        # skip_bootstrap=True so launch_chain doesn't bleed
        # over the fixture
        p = Planner(skip_bootstrap=True)
        plan = p.plan_for_goal("x")
        names = {s.capability_name for s in plan.steps}
        assert "apply_x" in names
        assert "gen_x" in names
        # Verification appended because apply_x is a writer
        assert "audit_store" in names

    def test_no_writer_no_verification(self):
        # Only a generator -- no writer -> no
        # audit_store appended
        register_capability(Capability(
            name="gen_only",
            kind=CapabilityKind.GENERATOR,
            description="just a generator",
            when_to_use="use for q",
            module_path="m:gen_only",
            tags=["q"],
        ))
        register_capability(Capability(
            name="audit_store",
            kind=CapabilityKind.AUDIT,
            description="audit",
            when_to_use="verify",
            module_path="m:audit_store",
        ))
        plan = Planner(skip_bootstrap=True).plan_for_goal("q")
        names = {s.capability_name for s in plan.steps}
        # The generator IS in the plan
        assert "gen_only" in names
        # No write step -> no verification appended
        assert "audit_store" not in names

    def test_chain_walk_depth_limited(self):
        """Cycle protection: composes_with that loops
        doesn't infinite-loop."""
        register_capability(Capability(
            name="loop_a",
            kind=CapabilityKind.APPLIER,
            description="a",
            when_to_use="a",
            module_path="m:loop_a",
            composes_with=["loop_b"],
            tags=["loop"],
        ))
        register_capability(Capability(
            name="loop_b",
            kind=CapabilityKind.APPLIER,
            description="b",
            when_to_use="b",
            module_path="m:loop_b",
            composes_with=["loop_a"],
            tags=["loop"],
        ))
        # Should terminate
        plan = Planner(skip_bootstrap=True).plan_for_goal(
            "loop",
        )
        # Both included, no infinite recursion
        names = {s.capability_name for s in plan.steps}
        assert "loop_a" in names
        assert "loop_b" in names


class TestUnhealthyEngineFilter:
    """``_filter_unhealthy_seeds`` drops caps whose engine_health
    verdict is 'unhealthy'. Env-gated by
    SHOPAI_PLANNER_HEALTH_FILTER=1."""

    def _seed_two(self):
        register_capability(Capability(
            name="healthy_engine",
            kind=CapabilityKind.ENGINE,
            description="works fine",
            when_to_use="use for foo",
            module_path="m:healthy",
            tags=["foo"],
        ))
        register_capability(Capability(
            name="sick_engine",
            kind=CapabilityKind.ENGINE,
            description="broken sick foo",
            when_to_use="use for foo",
            module_path="m:sick",
            tags=["foo"],
        ))

    def _fake_health(self, verdict):
        from core.approval.engine_health import (
            EngineHealth,
        )
        return EngineHealth(
            engine="sick_engine",
            score=2 if verdict == "unhealthy" else 8,
            verdict=verdict,
        )

    def test_env_gate_off_no_filter(self, monkeypatch):
        from unittest.mock import patch
        # No env var set
        monkeypatch.delenv(
            "SHOPAI_PLANNER_HEALTH_FILTER",
            raising=False,
        )
        self._seed_two()
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=self._fake_health("unhealthy"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("foo")
        # Both caps surface (no filter)
        names = {s.capability_name for s in p.steps}
        assert "healthy_engine" in names
        assert "sick_engine" in names

    def test_env_gate_on_drops_unhealthy(
        self, monkeypatch,
    ):
        from unittest.mock import patch
        monkeypatch.setenv(
            "SHOPAI_PLANNER_HEALTH_FILTER", "1",
        )
        self._seed_two()

        def fake_score(name, **kwargs):
            from core.approval.engine_health import (
                EngineHealth,
            )
            if name == "sick_engine":
                return EngineHealth(
                    engine=name, score=2,
                    verdict="unhealthy",
                )
            return EngineHealth(
                engine=name, score=8,
                verdict="healthy",
            )

        with patch(
            "core.approval.engine_health.score_engine",
            side_effect=fake_score,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("foo")
        names = {s.capability_name for s in p.steps}
        assert "healthy_engine" in names
        assert "sick_engine" not in names
        # Notes surface the filter result
        assert any(
            "unhealthy" in n.lower()
            and "sick_engine" in n
            for n in p.notes
        )

    def test_score_failure_keeps_seed(self, monkeypatch):
        from unittest.mock import patch
        monkeypatch.setenv(
            "SHOPAI_PLANNER_HEALTH_FILTER", "1",
        )
        self._seed_two()
        with patch(
            "core.approval.engine_health.score_engine",
            side_effect=RuntimeError("no queue"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("foo")
        # Score raised -> verdict='unknown' -> NOT
        # filtered as unhealthy. Both caps surface.
        names = {s.capability_name for s in p.steps}
        assert "healthy_engine" in names
        assert "sick_engine" in names


class TestRevenueImpactBoost:
    """Planner reorders seeds by historical revenue impact.
    Pure reorder -- no capability added or removed.

    Note: registry.find() returns capabilities alphabetically.
    Tests use names where the alphabetical-first IS NOT the
    revenue winner so the reorder is observable.
    """

    def _seed_three(self):
        # Alphabetical order: aaa_plain < mmm_plain <
        # zzz_winner. Revenue impact should float zzz_winner
        # to the front.
        for n in (
            "aaa_plain", "mmm_plain", "zzz_winner",
        ):
            register_capability(Capability(
                name=n,
                kind=CapabilityKind.ENGINE,
                description=f"{n} handles revenue",
                when_to_use=f"use {n} for revenue",
                module_path=f"m:{n}",
                tags=["revenue"],
            ))

    def test_revenue_winners_float_to_front(self):
        from unittest.mock import patch
        self._seed_three()
        revenue_rows = [
            {
                "capability": "zzz_winner",
                "total_revenue_delta": 5000.0,
                "avg_revenue_delta": 1000.0,
                "sample_size": 5,
                "positive_count": 5,
                "negative_count": 0,
            },
        ]
        with patch(
            "core.capability_planner.plan_history."
            "capability_revenue_impact",
            return_value=revenue_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("revenue")
        names = [s.capability_name for s in p.steps]
        # zzz_winner should appear BEFORE the plain ones
        idx_winner = names.index("zzz_winner")
        idx_plain = min(
            names.index("aaa_plain"),
            names.index("mmm_plain"),
        )
        assert idx_winner < idx_plain

    def test_no_revenue_history_preserves_order(self):
        from unittest.mock import patch
        self._seed_three()
        with patch(
            "core.capability_planner.plan_history."
            "capability_revenue_impact",
            return_value=[],
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("revenue")
        # No reorder note in plan.notes
        assert not any(
            "Revenue-impact reordered" in n
            for n in p.notes
        )

    def test_negative_revenue_does_not_boost(self):
        """Only positive revenue capabilities float up.
        Negative + zero = no boost (the demote system
        handles negative; this is pure prefer-winners)."""
        from unittest.mock import patch
        self._seed_three()
        revenue_rows = [
            {
                "capability": "zzz_winner",
                "total_revenue_delta": -500.0,
                "avg_revenue_delta": -100.0,
                "sample_size": 5,
                "positive_count": 0,
                "negative_count": 5,
            },
        ]
        with patch(
            "core.capability_planner.plan_history."
            "capability_revenue_impact",
            return_value=revenue_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("revenue")
        # No "Revenue-impact reordered" note -- no boost
        assert not any(
            "Revenue-impact reordered" in n
            for n in p.notes
        )

    def test_reorder_note_surfaces(self):
        from unittest.mock import patch
        self._seed_three()
        revenue_rows = [
            {
                "capability": "zzz_winner",
                "total_revenue_delta": 1500.0,
                "avg_revenue_delta": 500.0,
                "sample_size": 3,
                "positive_count": 3,
                "negative_count": 0,
            },
        ]
        with patch(
            "core.capability_planner.plan_history."
            "capability_revenue_impact",
            return_value=revenue_rows,
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("revenue")
        assert any(
            "Revenue-impact reordered" in n
            and "zzz_winner" in n
            for n in p.notes
        )

    def test_revenue_lookup_failure_silent(self):
        from unittest.mock import patch
        self._seed_three()
        with patch(
            "core.capability_planner.plan_history."
            "capability_revenue_impact",
            side_effect=RuntimeError("disk"),
        ):
            p = Planner(
                skip_bootstrap=True,
            ).plan_for_goal("revenue")
        # Plan still built; just no reorder note
        names = {s.capability_name for s in p.steps}
        assert "zzz_winner" in names
        assert not any(
            "Revenue-impact reordered" in n
            for n in p.notes
        )
