"""Tests for the tiered :class:`PolicyStore` (Wave 2 #1).

Covers:

* ``PolicyTier`` / ``PolicyVerdict`` enum shape
* HARD batch wraps the existing ``policy_checker`` (no edit required)
* MEDIUM + SOFT registration, edit-with-version-bump, and removal
* Evaluation pipeline: HARD → MEDIUM → SOFT, stopping on BLOCK
* MODIFY rules patch the action and accumulate modifications
* ``promote_soft_rule`` forces tier=SOFT and source="learned"
* JSONL audit log writes one record per evaluation
* ``evaluate_tiered`` convenience + default-store reset hook

These tests never touch the real ``.audit`` directory — each
test patches ``audit_path`` to a ``tmp_path`` file so runs are
fully isolated and parallelisable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.meta_governance import (
    PolicyDecision,
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
    evaluate_tiered,
    get_default_store,
    reset_default_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "policy_audit.jsonl"


@pytest.fixture
def store(audit_path: Path) -> PolicyStore:
    return PolicyStore(audit_path=str(audit_path))


@pytest.fixture(autouse=True)
def _reset_default_store():
    reset_default_store()
    yield
    reset_default_store()


# ---------------------------------------------------------------------------
# Enum shape
# ---------------------------------------------------------------------------


def test_policy_tier_values():
    assert PolicyTier.HARD.value == "hard"
    assert PolicyTier.MEDIUM.value == "medium"
    assert PolicyTier.SOFT.value == "soft"


def test_policy_verdict_values():
    assert PolicyVerdict.ALLOW.value == "allow"
    assert PolicyVerdict.MODIFY.value == "modify"
    assert PolicyVerdict.BLOCK.value == "block"


# ---------------------------------------------------------------------------
# HARD batch — wraps existing policy_checker without editing it
# ---------------------------------------------------------------------------


def test_hard_batch_allows_clean_action(store: PolicyStore):
    action = {
        "action_type": "launch_ad",
        "platform":    "facebook",
        "budget":      100.0,
    }
    context = {"daily_budget_limit": 1000.0}

    decision = store.evaluate_tiered(action, context)

    assert decision.hard_passed is True
    assert decision.failed_count == 0
    assert decision.verdict == PolicyVerdict.ALLOW


def test_hard_batch_blocks_disallowed_platform(store: PolicyStore):
    action = {
        "action_type": "launch_ad",
        "platform":    "mySpace",      # not in allowed list
        "budget":      100.0,
    }
    decision = store.evaluate_tiered(action, {})

    assert decision.hard_passed is False
    assert decision.failed_count >= 1
    assert decision.verdict == PolicyVerdict.BLOCK
    assert decision.final_tier == PolicyTier.HARD
    assert decision.final_rule_id == "HARD:policy_checker"


def test_hard_batch_blocks_blocked_keyword(store: PolicyStore):
    action = {
        "action_type": "publish_content",
        "title":       "Get rich quick!",
    }
    decision = store.evaluate_tiered(action, {})
    assert decision.verdict == PolicyVerdict.BLOCK
    assert decision.final_tier == PolicyTier.HARD


def test_hard_batch_blocks_high_impact_without_approval(store: PolicyStore):
    action = {"action_type": "delete_product"}
    decision = store.evaluate_tiered(action, {"explicit_approval": False})
    assert decision.verdict == PolicyVerdict.BLOCK


# ---------------------------------------------------------------------------
# MEDIUM rule — registration, matching, BLOCK
# ---------------------------------------------------------------------------


def _match_platform(platform: str):
    return (
        lambda action, context: str(
            action.get("platform", ""),
        ).lower() == platform
    )


def test_medium_block_stops_evaluation(store: PolicyStore):
    rule = PolicyRule(
        rule_id="MED-001",
        name="block_facebook_on_weekends",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="Facebook spend blocked on weekends",
        matcher=_match_platform("facebook"),
        verdict=PolicyVerdict.BLOCK,
    )
    store.register(rule)

    action = {
        "action_type": "launch_ad",
        "platform":    "facebook",
        "budget":      100.0,
    }
    decision = store.evaluate_tiered(action, {})

    assert decision.verdict == PolicyVerdict.BLOCK
    assert decision.final_tier == PolicyTier.MEDIUM
    assert decision.final_rule_id == "MED-001"


def test_medium_allow_explicit_pass(store: PolicyStore):
    rule = PolicyRule(
        rule_id="MED-002",
        name="explicit_allow",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="Explicit allow for tiktok",
        matcher=_match_platform("tiktok"),
        verdict=PolicyVerdict.ALLOW,
    )
    store.register(rule)

    action = {
        "action_type": "launch_ad",
        "platform":    "tiktok",
        "budget":      100.0,
    }
    decision = store.evaluate_tiered(action, {})
    assert decision.verdict == PolicyVerdict.ALLOW


# ---------------------------------------------------------------------------
# MODIFY rules — action patching
# ---------------------------------------------------------------------------


def test_medium_modify_patches_action(store: PolicyStore):
    def cap_budget(action, context):
        return {"budget": min(float(action.get("budget", 0)), 50.0)}

    rule = PolicyRule(
        rule_id="MED-003",
        name="cap_budget_at_50",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="Cap any ad budget at $50",
        matcher=lambda a, c: a.get("action_type") == "launch_ad",
        verdict=PolicyVerdict.MODIFY,
        modify_fn=cap_budget,
    )
    store.register(rule)

    action = {
        "action_type": "launch_ad",
        "platform":    "facebook",
        "budget":      500.0,
    }
    decision = store.evaluate_tiered(action, {})

    assert decision.verdict == PolicyVerdict.MODIFY
    assert decision.action["budget"] == 50.0
    assert decision.modifications == {"budget": 50.0}
    assert decision.final_rule_id == "MED-003"


def test_multiple_modify_rules_accumulate(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="MED-010",
        name="set_currency",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="force currency",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.MODIFY,
        modify_fn=lambda a, c: {"currency": "USD"},
    ))
    store.register(PolicyRule(
        rule_id="MED-011",
        name="add_tag",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="force tag",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.MODIFY,
        modify_fn=lambda a, c: {"tag": "gov_patched"},
    ))

    decision = store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )
    assert decision.verdict == PolicyVerdict.MODIFY
    assert decision.action["currency"] == "USD"
    assert decision.action["tag"] == "gov_patched"
    assert decision.modifications == {
        "currency": "USD",
        "tag":      "gov_patched",
    }


# ---------------------------------------------------------------------------
# SOFT tier — lowest authority
# ---------------------------------------------------------------------------


def test_soft_rule_runs_after_medium(store: PolicyStore):
    calls: list[str] = []
    store.register(PolicyRule(
        rule_id="MED-100",
        name="med",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="medium rule",
        matcher=lambda a, c: (calls.append("medium") or False),
        verdict=PolicyVerdict.ALLOW,
    ))
    store.register(PolicyRule(
        rule_id="SOFT-100",
        name="soft",
        tier=PolicyTier.SOFT,
        source="learned",
        description="soft rule",
        matcher=lambda a, c: (calls.append("soft") or False),
        verdict=PolicyVerdict.ALLOW,
    ))

    store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )
    # MEDIUM must run before SOFT
    assert calls == ["medium", "soft"]


def test_soft_block_final_tier(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="SOFT-200",
        name="block_recent_failure",
        tier=PolicyTier.SOFT,
        source="learned",
        description="block pattern that failed 3x last week",
        matcher=lambda a, c: a.get("_repeat_failure") is True,
        verdict=PolicyVerdict.BLOCK,
    ))
    decision = store.evaluate_tiered(
        {
            "action_type":     "launch_ad",
            "platform":        "facebook",
            "budget":          20,
            "_repeat_failure": True,
        },
        {},
    )
    assert decision.verdict == PolicyVerdict.BLOCK
    assert decision.final_tier == PolicyTier.SOFT
    assert decision.final_rule_id == "SOFT-200"


# ---------------------------------------------------------------------------
# Registration mechanics
# ---------------------------------------------------------------------------


def test_register_hard_tier_rejected(store: PolicyStore):
    with pytest.raises(ValueError, match="HARD rules are immutable"):
        store.register(PolicyRule(
            rule_id="HARD-X",
            name="x",
            tier=PolicyTier.HARD,
            source="operator",
            description="nope",
            matcher=lambda a, c: True,
            verdict=PolicyVerdict.BLOCK,
        ))


def test_re_registration_bumps_version(store: PolicyStore):
    r1 = PolicyRule(
        rule_id="MED-500",
        name="r",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="v1",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.ALLOW,
    )
    store.register(r1)
    r2 = PolicyRule(
        rule_id="MED-500",
        name="r",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="v2",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.ALLOW,
    )
    store.register(r2)

    rules = store.list_rules(PolicyTier.MEDIUM)
    med_500 = [r for r in rules if r.rule_id == "MED-500"]
    assert len(med_500) == 1
    assert med_500[0].version == 2


def test_bump_version(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="MED-600",
        name="r",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="v1",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.ALLOW,
    ))
    new_version = store.bump_version("MED-600")
    assert new_version == 2
    assert store.bump_version("nonexistent") is None


def test_remove_non_hard(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="MED-700",
        name="r",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="v1",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.ALLOW,
    ))
    assert store.remove("MED-700") is True
    assert store.remove("MED-700") is False


def test_list_rules_by_tier(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="MED-800",
        name="m",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.ALLOW,
    ))
    store.register(PolicyRule(
        rule_id="SOFT-800",
        name="s",
        tier=PolicyTier.SOFT,
        source="learned",
        description="",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.ALLOW,
    ))

    assert [r.rule_id for r in store.list_rules(PolicyTier.MEDIUM)] == [
        "MED-800",
    ]
    assert [r.rule_id for r in store.list_rules(PolicyTier.SOFT)] == [
        "SOFT-800",
    ]
    assert len(store.list_rules()) == 2


# ---------------------------------------------------------------------------
# promote_soft_rule — reflection synthesizer hook
# ---------------------------------------------------------------------------


def test_promote_soft_rule_forces_tier_and_source(store: PolicyStore):
    # Source rule is declared MEDIUM — promote should coerce to SOFT.
    candidate = PolicyRule(
        rule_id="PROMO-1",
        name="block_recurring_pattern",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="three failures in a week",
        matcher=lambda a, c: False,
        verdict=PolicyVerdict.BLOCK,
    )
    store.promote_soft_rule(candidate)

    soft = store.list_rules(PolicyTier.SOFT)
    assert len(soft) == 1
    assert soft[0].rule_id == "PROMO-1"
    assert soft[0].tier == PolicyTier.SOFT
    assert soft[0].source == "learned"
    # Original candidate object is untouched
    assert candidate.tier == PolicyTier.MEDIUM


# ---------------------------------------------------------------------------
# Audit log — JSONL
# ---------------------------------------------------------------------------


def test_audit_log_appends_one_line_per_evaluation(
    store: PolicyStore, audit_path: Path,
):
    store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )
    store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "mySpace", "budget": 20},
        {},
    )

    assert audit_path.exists()
    lines = [
        line
        for line in audit_path.read_text().splitlines()
        if line.strip()
    ]
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["verdict"] == "allow"
    assert first["action_type"] == "launch_ad"
    assert "inputs_hash" in first
    assert isinstance(first["trace"], list)

    second = json.loads(lines[1])
    assert second["verdict"] == "block"
    assert second["final_tier"] == "hard"


def test_audit_log_includes_rule_metadata(
    store: PolicyStore, audit_path: Path,
):
    store.register(PolicyRule(
        rule_id="MED-AUD",
        name="patch_currency",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="force USD",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.MODIFY,
        modify_fn=lambda a, c: {"currency": "USD"},
    ))
    store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )

    entries = store.read_audit(limit=10)
    assert entries
    trace = entries[0]["trace"]
    med_entry = [e for e in trace if e.get("rule_id") == "MED-AUD"]
    assert med_entry
    assert med_entry[0]["version"] == 1
    assert med_entry[0]["source"] == "operator"
    assert med_entry[0]["modifications"] == {"currency": "USD"}


def test_audit_read_returns_newest_first(
    store: PolicyStore,
):
    for i in range(3):
        store.evaluate_tiered(
            {
                "action_type": "launch_ad",
                "platform":    "facebook",
                "budget":      float(i + 1),
            },
            {},
        )
    entries = store.read_audit(limit=2)
    assert len(entries) == 2
    # Both should be "allow" and distinct (distinct inputs_hash).
    hashes = {e["inputs_hash"] for e in entries}
    assert len(hashes) == 2


# ---------------------------------------------------------------------------
# Defensive: matcher errors don't crash the pipeline
# ---------------------------------------------------------------------------


def test_matcher_exception_is_isolated(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="MED-ERR",
        name="buggy",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="crash",
        matcher=lambda a, c: 1 / 0,  # boom
        verdict=PolicyVerdict.BLOCK,
    ))

    # Should NOT raise — the buggy rule is skipped and the
    # evaluation continues.
    decision = store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )
    assert decision.verdict == PolicyVerdict.ALLOW

    err_entries = [
        e for e in decision.trace if e.get("rule_id") == "MED-ERR"
    ]
    assert err_entries
    assert "error" in err_entries[0]
    assert "ZeroDivisionError" in err_entries[0]["error"]


def test_modify_function_error_recorded(store: PolicyStore):
    store.register(PolicyRule(
        rule_id="MED-MOD-ERR",
        name="buggy_modify",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="crash",
        matcher=lambda a, c: True,
        verdict=PolicyVerdict.MODIFY,
        modify_fn=lambda a, c: 1 / 0,
    ))

    decision = store.evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )
    # modify_fn failed so no modification accumulated; the running
    # verdict stays ALLOW.
    assert decision.verdict == PolicyVerdict.ALLOW
    assert decision.modifications == {}
    entry = next(
        e for e in decision.trace if e.get("rule_id") == "MED-MOD-ERR"
    )
    assert "modify_error" in entry


# ---------------------------------------------------------------------------
# Module-level convenience + default store
# ---------------------------------------------------------------------------


def test_evaluate_tiered_uses_default_store(tmp_path: Path, monkeypatch):
    # Redirect the default store's audit path to tmp so we don't
    # pollute the real .audit dir.
    monkeypatch.setattr(
        "engines.meta_governance.policy_store._DEFAULT_AUDIT_PATH",
        str(tmp_path / "default_audit.jsonl"),
    )
    reset_default_store()

    store = get_default_store()
    assert isinstance(store, PolicyStore)

    decision = evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
    )
    assert isinstance(decision, PolicyDecision)
    assert decision.verdict == PolicyVerdict.ALLOW


def test_evaluate_tiered_accepts_explicit_store(store: PolicyStore):
    decision = evaluate_tiered(
        {"action_type": "launch_ad", "platform": "facebook", "budget": 20},
        {},
        store=store,
    )
    assert decision.verdict == PolicyVerdict.ALLOW


def test_reset_default_store_gives_fresh_instance(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engines.meta_governance.policy_store._DEFAULT_AUDIT_PATH",
        str(tmp_path / "default_audit.jsonl"),
    )
    first = get_default_store()
    reset_default_store()
    second = get_default_store()
    assert first is not second
