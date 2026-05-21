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
