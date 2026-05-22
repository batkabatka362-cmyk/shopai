"""Tests for ``core.capability_planner.auto_demote``.

The bridge from ``plan_history.capability_degradations`` to
``capability_overrides.demote``. Coverage:

  - Env-var gate (default OFF; reads + previews still work)
  - Threshold parsing (default + override + invalid)
  - find_demote_candidates filters already-demoted +
    promoted entries; preserves drop-desc ordering
  - maybe_auto_demote_degraded skips blocked entries,
    writes ``demote`` overrides with audit-trail reason
  - Pattern J: under pytest the writer short-circuits
    unless the guard is patched
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.capability_planner import auto_demote


_BRIDGE_ENV_VARS = (
    "SHOPAI_AUTO_DEMOTE_DEGRADED",
    "SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD",
    "SHOPAI_AUTO_DEMOTE_MIN_RECENT_SAMPLE",
    "SHOPAI_AUTO_DEMOTE_RECENT_WINDOW_DAYS",
    "SHOPAI_AUTO_DEMOTE_BASELINE_WINDOW_DAYS",
    "SHOPAI_AUTO_DEMOTE_RECOVERY_THRESHOLD",
)


@pytest.fixture(autouse=True)
def _clean_env():
    """Strip every bridge env var around each test so default
    paths exercise the documented defaults.

    Pops at setup AND at teardown -- if a test sets one of
    these vars (without saving via monkeypatch), the teardown
    pop ensures it doesn't leak to later tests in other files.
    """
    preserved: dict[str, str | None] = {}
    for k in _BRIDGE_ENV_VARS:
        preserved[k] = os.environ.pop(k, None)
    yield
    # Always strip first -- the test may have set new values
    for k in _BRIDGE_ENV_VARS:
        os.environ.pop(k, None)
    # Then restore anything that was set BEFORE the test
    for k, v in preserved.items():
        if v is not None:
            os.environ[k] = v


class TestEnvGates:

    def test_disabled_by_default(self):
        assert auto_demote.is_enabled() is False

    def test_enabled_by_env(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DEGRADED"] = "1"
        assert auto_demote.is_enabled() is True

    def test_drop_threshold_default(self):
        assert auto_demote.drop_threshold() == 0.4

    def test_drop_threshold_env_override(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD"] = "0.6"
        assert auto_demote.drop_threshold() == 0.6

    def test_drop_threshold_invalid_falls_back(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD"] = "abc"
        assert auto_demote.drop_threshold() == 0.4

    def test_drop_threshold_non_positive_falls_back(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD"] = "-0.1"
        assert auto_demote.drop_threshold() == 0.4

    def test_min_recent_sample_default_and_override(self):
        assert auto_demote.min_recent_sample() == 3
        os.environ["SHOPAI_AUTO_DEMOTE_MIN_RECENT_SAMPLE"] = "5"
        assert auto_demote.min_recent_sample() == 5

    def test_recent_window_days_default_and_override(self):
        assert auto_demote.recent_window_days() == 7
        os.environ["SHOPAI_AUTO_DEMOTE_RECENT_WINDOW_DAYS"] = "3"
        assert auto_demote.recent_window_days() == 3

    def test_baseline_window_days_default_and_override(self):
        assert auto_demote.baseline_window_days() == 30
        os.environ[
            "SHOPAI_AUTO_DEMOTE_BASELINE_WINDOW_DAYS"
        ] = "14"
        assert auto_demote.baseline_window_days() == 14

    def test_config_summary(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DEGRADED"] = "1"
        os.environ["SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD"] = "0.5"
        cfg = auto_demote.config_summary()
        assert cfg["enabled"] is True
        assert cfg["drop_threshold"] == 0.5
        assert cfg["min_recent_sample"] == 3
        assert cfg["recent_window_days"] == 7
        assert cfg["baseline_window_days"] == 30


class TestFindCandidates:
    """Read-only previews never write -- safe under default
    Pattern J guard."""

    def _fake_overrides(self, promoted=None, demoted=None):
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

    def test_returns_empty_when_no_degradations(self):
        with patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(),
        ):
            out = auto_demote.find_demote_candidates()
        assert out == []

    def test_returns_all_with_blocked_flags(self):
        degradations = [
            {
                "capability": "cap_a",
                "baseline_rate": 0.9,
                "recent_rate": 0.3,
                "drop": 0.6,
                "recent_samples": 5,
                "baseline_samples": 20,
            },
            {
                "capability": "cap_b",
                "baseline_rate": 0.8,
                "recent_rate": 0.3,
                "drop": 0.5,
                "recent_samples": 4,
                "baseline_samples": 15,
            },
            {
                "capability": "cap_c",
                "baseline_rate": 0.7,
                "recent_rate": 0.3,
                "drop": 0.4,
                "recent_samples": 3,
                "baseline_samples": 10,
            },
        ]
        with patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=degradations,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(
                promoted=["cap_a"],
                demoted=["cap_b"],
            ),
        ):
            out = auto_demote.find_demote_candidates()
        assert len(out) == 3
        assert out[0]["capability"] == "cap_a"
        assert out[0]["blocked_by"] == "promoted"
        assert out[1]["capability"] == "cap_b"
        assert out[1]["blocked_by"] == "already_demoted"
        assert out[2]["capability"] == "cap_c"
        assert out[2]["blocked_by"] is None

    def test_threshold_overrides_passed_through(self):
        called = {}

        def fake_degradations(**kwargs):
            called.update(kwargs)
            return []

        with patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            side_effect=fake_degradations,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(),
        ):
            auto_demote.find_demote_candidates(
                drop=0.55,
                min_recent=4,
                recent_days=5,
                baseline_days=21,
            )
        assert called["drop_threshold"] == 0.55
        assert called["min_recent_sample"] == 4
        assert called["recent_window_seconds"] == 5 * 86400
        assert called["baseline_window_seconds"] == 21 * 86400
        # baseline floor: max(min_recent*2, 5) -> 8 here
        assert called["min_baseline_sample"] == 8


class TestMaybeAutoDemote:

    def _fake_overrides(self, promoted=None, demoted=None):
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

    def test_pattern_j_under_pytest_short_circuits(self):
        """Default Pattern J guard means even with env set the
        bridge writes nothing under pytest."""
        os.environ["SHOPAI_AUTO_DEMOTE_DEGRADED"] = "1"
        with patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=[{
                "capability": "x",
                "baseline_rate": 0.9,
                "recent_rate": 0.1,
                "drop": 0.8,
                "recent_samples": 5,
                "baseline_samples": 20,
            }],
        ):
            applied = auto_demote.maybe_auto_demote_degraded()
        assert applied == []

    def test_disabled_returns_empty_even_when_candidates_exist(self):
        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=[{
                "capability": "x",
                "baseline_rate": 0.9,
                "recent_rate": 0.1,
                "drop": 0.8,
                "recent_samples": 5,
                "baseline_samples": 20,
            }],
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(),
        ):
            applied = auto_demote.maybe_auto_demote_degraded()
        assert applied == []

    def test_enabled_applies_to_unblocked_only(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DEGRADED"] = "1"
        degradations = [
            {
                "capability": "cap_promoted",
                "baseline_rate": 0.9,
                "recent_rate": 0.1,
                "drop": 0.8,
                "recent_samples": 5,
                "baseline_samples": 20,
            },
            {
                "capability": "cap_already_demoted",
                "baseline_rate": 0.8,
                "recent_rate": 0.1,
                "drop": 0.7,
                "recent_samples": 4,
                "baseline_samples": 15,
            },
            {
                "capability": "cap_new",
                "baseline_rate": 0.7,
                "recent_rate": 0.2,
                "drop": 0.5,
                "recent_samples": 3,
                "baseline_samples": 10,
            },
        ]
        demote_calls: list[tuple[str, str]] = []

        def fake_demote(name, reason=""):
            demote_calls.append((name, reason))
            return True

        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=degradations,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(
                promoted=["cap_promoted"],
                demoted=["cap_already_demoted"],
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.demote",
            side_effect=fake_demote,
        ):
            applied = auto_demote.maybe_auto_demote_degraded()
        assert len(applied) == 1
        assert applied[0]["capability"] == "cap_new"
        assert applied[0]["drop"] == 0.5
        assert applied[0]["recent_rate"] == 0.2
        assert "auto_demote_degraded" in applied[0]["reason"]
        assert "drop=0.500" in applied[0]["reason"]
        # Only cap_new was actually demoted
        assert demote_calls == [
            ("cap_new", applied[0]["reason"]),
        ]

    def test_demote_io_failure_skips_row(self):
        os.environ["SHOPAI_AUTO_DEMOTE_DEGRADED"] = "1"
        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=[{
                "capability": "cap_x",
                "baseline_rate": 0.9,
                "recent_rate": 0.1,
                "drop": 0.8,
                "recent_samples": 5,
                "baseline_samples": 20,
            }],
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(),
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.demote",
            return_value=False,  # write blocked / failed
        ):
            applied = auto_demote.maybe_auto_demote_degraded()
        assert applied == []


class TestAnnotateDegradations:
    """``annotate_degradations`` tags each row with its
    bridge status: auto_demoted / would_demote / watching."""

    def _fake_overrides(self, promoted=None, demoted=None):
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

    def test_empty_input_returns_empty(self):
        assert auto_demote.annotate_degradations([]) == []

    def test_auto_demoted_tag_for_existing_demote(self):
        degs = [{
            "capability": "cap_x",
            "baseline_rate": 0.9,
            "recent_rate": 0.1,
            "drop": 0.8,
            "recent_samples": 5,
            "baseline_samples": 20,
        }]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(
                demoted=["cap_x"],
            ),
        ):
            out = auto_demote.annotate_degradations(degs)
        assert out[0]["bridge_status"] == "auto_demoted"
        # Original fields preserved
        assert out[0]["drop"] == 0.8

    def test_would_demote_tag_above_threshold(self):
        degs = [{
            "capability": "cap_severe",
            "baseline_rate": 0.9,
            "recent_rate": 0.3,
            "drop": 0.6,
            "recent_samples": 5,
            "baseline_samples": 20,
        }]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(),
        ):
            out = auto_demote.annotate_degradations(degs)
        assert out[0]["bridge_status"] == "would_demote"

    def test_watching_tag_below_severe_threshold(self):
        degs = [{
            "capability": "cap_mild",
            "baseline_rate": 0.9,
            "recent_rate": 0.6,
            "drop": 0.3,
            "recent_samples": 5,
            "baseline_samples": 20,
        }]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(),
        ):
            out = auto_demote.annotate_degradations(degs)
        assert out[0]["bridge_status"] == "watching"

    def test_promoted_skipped_from_would_demote(self):
        """Promoted capability with severe drop stays
        ``watching`` -- the bridge wouldn't auto-demote it
        because the promote takes precedence."""
        degs = [{
            "capability": "cap_promoted",
            "baseline_rate": 0.9,
            "recent_rate": 0.1,
            "drop": 0.8,
            "recent_samples": 5,
            "baseline_samples": 20,
        }]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(
                promoted=["cap_promoted"],
            ),
        ):
            out = auto_demote.annotate_degradations(degs)
        assert out[0]["bridge_status"] == "watching"

    def test_mixed_tiers_preserved_in_order(self):
        degs = [
            {
                "capability": "auto_already",
                "baseline_rate": 0.9, "recent_rate": 0.1,
                "drop": 0.8, "recent_samples": 5,
                "baseline_samples": 20,
            },
            {
                "capability": "severe_new",
                "baseline_rate": 0.9, "recent_rate": 0.3,
                "drop": 0.6, "recent_samples": 5,
                "baseline_samples": 20,
            },
            {
                "capability": "mild",
                "baseline_rate": 0.9, "recent_rate": 0.65,
                "drop": 0.25, "recent_samples": 5,
                "baseline_samples": 20,
            },
        ]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._fake_overrides(
                demoted=["auto_already"],
            ),
        ):
            out = auto_demote.annotate_degradations(degs)
        assert [r["bridge_status"] for r in out] == [
            "auto_demoted",
            "would_demote",
            "watching",
        ]
        # Input order preserved
        assert [r["capability"] for r in out] == [
            "auto_already", "severe_new", "mild",
        ]


class TestRecoveryThreshold:

    def test_default(self):
        assert auto_demote.recovery_threshold() == 0.7

    def test_env_override(self):
        os.environ[
            "SHOPAI_AUTO_DEMOTE_RECOVERY_THRESHOLD"
        ] = "0.85"
        assert auto_demote.recovery_threshold() == 0.85

    def test_out_of_range_falls_back(self):
        os.environ[
            "SHOPAI_AUTO_DEMOTE_RECOVERY_THRESHOLD"
        ] = "1.5"
        assert auto_demote.recovery_threshold() == 0.7
        os.environ[
            "SHOPAI_AUTO_DEMOTE_RECOVERY_THRESHOLD"
        ] = "-0.1"
        assert auto_demote.recovery_threshold() == 0.7

    def test_invalid_falls_back(self):
        os.environ[
            "SHOPAI_AUTO_DEMOTE_RECOVERY_THRESHOLD"
        ] = "abc"
        assert auto_demote.recovery_threshold() == 0.7

    def test_config_summary_includes_recovery(self):
        cfg = auto_demote.config_summary()
        assert cfg["recovery_threshold"] == 0.7


class TestFindReleaseCandidates:

    def _override(
        self, name, kind="demote", reason="", at=0.0,
    ):
        from core.capability_planner.\
capability_overrides import CapabilityOverride
        return CapabilityOverride(
            name=name, kind=kind, reason=reason,
            recorded_at=at,
        )

    def _overrides_for(self, *entries):
        from core.capability_planner.\
capability_overrides import CapabilityOverrides
        return CapabilityOverrides(entries=list(entries))

    def test_no_bridge_demotes_returns_empty(self):
        # Only manual demote present -- bridge entries
        # required.
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "manual", reason="operator says",
                ),
            ),
        ):
            out = auto_demote.find_release_candidates()
        assert out == []

    def test_promote_entries_ignored(self):
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "winner", kind="promote",
                    reason="auto_demote_degraded: stale",
                ),
            ),
        ):
            out = auto_demote.find_release_candidates()
        assert out == []

    def test_demoted_with_no_recent_samples_skipped(self):
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "cap_a",
                    reason="auto_demote_degraded: ...",
                ),
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=[],
        ):
            out = auto_demote.find_release_candidates()
        assert out == []

    def test_demoted_below_recovery_threshold_skipped(self):
        leaderboard = [{
            "capability": "cap_a",
            "executed_count": 5,
            "success_count": 2,
            "success_rate": 0.4,
        }]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "cap_a",
                    reason="auto_demote_degraded: ...",
                ),
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=leaderboard,
        ):
            out = auto_demote.find_release_candidates()
        # 0.4 < 0.7 default -> not a candidate
        assert out == []

    def test_recovered_capability_returned(self):
        leaderboard = [
            {
                "capability": "recovered",
                "executed_count": 5,
                "success_count": 5,
                "success_rate": 1.0,
            },
            {
                "capability": "still_bad",
                "executed_count": 5,
                "success_count": 1,
                "success_rate": 0.2,
            },
        ]
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "recovered",
                    reason="auto_demote_degraded: A",
                    at=100.0,
                ),
                self._override(
                    "still_bad",
                    reason="auto_demote_degraded: B",
                    at=200.0,
                ),
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=leaderboard,
        ):
            out = auto_demote.find_release_candidates()
        assert len(out) == 1
        assert out[0]["capability"] == "recovered"
        assert out[0]["recent_rate"] == 1.0
        assert out[0]["recent_samples"] == 5
        assert out[0]["demoted_at"] == 100.0
        assert out[0]["demote_reason"].startswith(
            "auto_demote_degraded",
        )


class TestMaybeReleaseRecovered:

    def _override(self, name, reason="", at=0.0):
        from core.capability_planner.\
capability_overrides import CapabilityOverride
        return CapabilityOverride(
            name=name, kind="demote", reason=reason,
            recorded_at=at,
        )

    def _overrides_for(self, *entries):
        from core.capability_planner.\
capability_overrides import CapabilityOverrides
        return CapabilityOverrides(entries=list(entries))

    def test_pattern_j_under_pytest(self):
        # Even with recovered candidates available, the
        # default Pattern J guard short-circuits writes.
        with patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "recovered",
                    reason="auto_demote_degraded: ...",
                ),
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=[{
                "capability": "recovered",
                "executed_count": 5,
                "success_count": 5,
                "success_rate": 1.0,
            }],
        ):
            released = auto_demote.maybe_release_recovered()
        assert released == []

    def test_clears_recovered_demotes(self):
        cleared: list[str] = []

        def fake_clear(name):
            cleared.append(name)
            return True

        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "recovered",
                    reason="auto_demote_degraded: ...",
                ),
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=[{
                "capability": "recovered",
                "executed_count": 5,
                "success_count": 5,
                "success_rate": 1.0,
            }],
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.clear",
            side_effect=fake_clear,
        ):
            released = auto_demote.maybe_release_recovered()
        assert len(released) == 1
        assert released[0]["capability"] == "recovered"
        assert cleared == ["recovered"]

    def test_clear_failure_skipped(self):
        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=self._overrides_for(
                self._override(
                    "recovered",
                    reason="auto_demote_degraded: ...",
                ),
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=[{
                "capability": "recovered",
                "executed_count": 5,
                "success_count": 5,
                "success_rate": 1.0,
            }],
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.clear",
            return_value=False,
        ):
            released = auto_demote.maybe_release_recovered()
        assert released == []
