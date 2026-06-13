"""Fifth batch: institutional audits.

The 7 audits documented in CLAUDE.md (Pattern K / Y / I / J /
Z / Q + OAuth health) catch dev-facing failure modes:
silent-swallowing exceptions, missing scope declarations,
unreached engines, writers that skip Pattern Z recording,
engines returning malformed envelopes, etc.

Registering them makes the audits **discoverable** the same
way operator-facing engines are: ``shopai capabilities find
audit`` returns the full audit suite; ``shopai plan
"verify codebase"`` surfaces the relevant audits.

These complement ``audit_store`` (registered in the
launch-chain batch), which is store-facing rather than
dev-facing. ``shopai audit`` is the consolidated runner that
runs all of them in one shot.
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    register_capability,
)


def register_all() -> None:
    """Idempotent batch registration of the 7 institutional
    audits + the consolidated runner."""

    register_capability(Capability(
        name="pattern_k_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "AST audit: every enqueued action_type has a "
            "dispatcher. Catches enqueue-with-no-runner "
            "drift."
        ),
        when_to_use=(
            "Use when the goal involves verifying that "
            "every approval-queue action_type can actually "
            "be executed -- catches dispatcher rot."
        ),
        module_path=(
            "core.approval._pattern_k_audit:audit_pattern_k"
        ),
        tags=["audit", "ci-gate", "pattern-k"],
        cli_commands=["shopai pattern-k-audit"],
    ))

    register_capability(Capability(
        name="pattern_y_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "Runtime audit: every ``Capability.SHOPIFY_*`` "
            "enum has at least one adapter declaring it."
        ),
        when_to_use=(
            "Use when the goal involves verifying adapter "
            "coverage of the Capability enum -- catches "
            "orphan capabilities (declared but unreachable)."
        ),
        module_path=(
            "core.adapters.shopify._pattern_y_audit:"
            "audit_pattern_y"
        ),
        tags=["audit", "ci-gate", "adapters", "pattern-y"],
        cli_commands=["shopai capabilities-audit"],
    ))

    register_capability(Capability(
        name="pattern_i_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "AST audit: every engine's "
            "``capability_name=`` references a real "
            "Capability enum + adapter."
        ),
        when_to_use=(
            "Use when the goal involves verifying engine "
            "hydrators reach a real adapter -- catches "
            "name typos / dead capability_name links."
        ),
        module_path=(
            "engines._pattern_i_audit:audit_pattern_i"
        ),
        tags=["audit", "ci-gate", "engines", "pattern-i"],
        cli_commands=["shopai engines-capability-audit"],
    ))

    register_capability(Capability(
        name="pattern_j_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "AST audit: writes to learning singletons "
            "(MemoryIntel / DataArch / LearningLoop) are "
            "test-environment-guarded."
        ),
        when_to_use=(
            "Use when the goal involves verifying that "
            "test runs don't pollute the learning DBs -- "
            "catches missing PYTEST_CURRENT_TEST guards."
        ),
        module_path=(
            "engines._pattern_j_audit:audit_pattern_j"
        ),
        tags=["audit", "ci-gate", "pattern-j",
              "test-safety"],
        cli_commands=["shopai pattern-j-audit"],
    ))

    register_capability(Capability(
        name="pattern_z_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "AST audit: every writer module "
            "(*_applier / *_minter / *_payer) calls "
            "``record_writeback``."
        ),
        when_to_use=(
            "Use when the goal involves verifying that "
            "every Shopify mutation flows into Phase 8 "
            "(MemoryIntel + DataArch + LearningLoop) -- "
            "catches writers that bypass the learning loop."
        ),
        module_path=(
            "engines._pattern_z_audit:audit_pattern_z"
        ),
        tags=["audit", "ci-gate", "pattern-z", "writebacks"],
        cli_commands=["shopai pattern-z-audit"],
    ))

    register_capability(Capability(
        name="pattern_q_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "Runtime audit: every engine's ``run()`` "
            "returns the canonical {status, data, meta, "
            "error} envelope."
        ),
        when_to_use=(
            "Use when the goal involves verifying engine "
            "output contract -- catches drift in the "
            "envelope schema across the engine fleet."
        ),
        module_path=(
            "engines._pattern_q_audit:audit_pattern_q"
        ),
        tags=["audit", "ci-gate", "pattern-q", "engines",
              "envelope"],
        cli_commands=["shopai pattern-q-audit"],
    ))

    # Pattern S audit (silent except: pass) was removed from
    # this branch -- the module engines/_pattern_s_audit.py
    # no longer exists, so the registry entry is dead. If the
    # audit gets re-introduced on a future branch, restore
    # the registration here.

    register_capability(Capability(
        name="oauth_audit",
        kind=CapabilityKind.AUDIT,
        description=(
            "Runtime audit: every adapter declares "
            "``required_scopes`` (or ``scope_independent``)."
        ),
        when_to_use=(
            "Use when the goal involves verifying OAuth "
            "scope coverage across the adapter fleet -- "
            "catches adapters that would fail at runtime "
            "due to missing scope declarations."
        ),
        module_path=(
            "core.adapters.shopify.scope_health:audit_oauth"
        ),
        tags=["audit", "ci-gate", "oauth", "scopes",
              "adapters"],
        cli_commands=["shopai shopify-scopes-audit"],
    ))

    register_capability(Capability(
        name="scope_health_check",
        kind=CapabilityKind.AUDIT,
        description=(
            "Live drift check: compares declared scopes vs "
            "what the installed Shopify app actually has "
            "granted."
        ),
        when_to_use=(
            "Use when the goal involves verifying the live "
            "Shopify install has every scope declared in "
            "the manifest -- catches over-/under-grant "
            "drift."
        ),
        module_path=(
            "core.adapters.shopify.scope_health:compare_to_live"
        ),
        tags=["audit", "live-check", "oauth", "scopes",
              "drift"],
        cli_commands=["shopai shopify-scopes-live-check"],
    ))

    register_capability(Capability(
        name="audit_all",
        kind=CapabilityKind.ORCHESTRATOR,
        description=(
            "Consolidated runner: runs every institutional "
            "audit in one shot + emits a unified report."
        ),
        when_to_use=(
            "Use when the goal involves a comprehensive "
            "codebase health check -- runs all 7 audits + "
            "the live scope drift in one CLI call."
        ),
        module_path="cli:_cmd_audit_all",
        composes_with=[
            "pattern_k_audit", "pattern_y_audit",
            "pattern_i_audit", "pattern_j_audit",
            "pattern_z_audit", "pattern_q_audit",
            "oauth_audit",
            "scope_health_check",
        ],
        tags=["audit", "ci-gate", "consolidated"],
        cli_commands=["shopai audit"],
    ))
