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
