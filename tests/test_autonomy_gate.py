"""W963-148: autonomy gate tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engines.autonomy_gate import (
    AutonomyGateEngine,
    AutonomyGateReport,
    StoreStability,
    check_autonomy_gate,
    is_autonomy_unlocked,
)
from engines.autonomy_gate.threshold import (
    _DEFAULT_MIN_CYCLES,
    _DEFAULT_PROOF_DAYS,
    _DEFAULT_REQUIRED_STORES,
    _resolve_int_env,
)


class TestEnvResolution:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("MY_TEST_VAR", raising=False)
        assert _resolve_int_env(
            "MY_TEST_VAR", 42,
        ) == 42

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_VAR", "5")
        assert _resolve_int_env(
            "MY_TEST_VAR", 42,
        ) == 5

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_VAR", "garbage")
        assert _resolve_int_env(
            "MY_TEST_VAR", 42,
        ) == 42

    def test_zero_falls_back(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_VAR", "0")
        assert _resolve_int_env(
            "MY_TEST_VAR", 42,
        ) == 42


class TestStoreStability:
    def test_total_incidents_sum(self):
        s = StoreStability(
            store_id="x",
            cycle_count=20,
            cycle_errors=1,
            autopause_fires=2,
            refund_anomalies=0,
            autonomy_alerts=3,
            rejected_actions=4,
        )
        assert s.total_incidents == 10

    def test_stable_requires_min_cycles_and_zero_incidents(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES", "10",
        )
        # 10 cycles + 0 incidents -> stable
        s = StoreStability(
            store_id="x", cycle_count=10,
        )
        assert s.is_stable is True

    def test_unstable_when_below_min_cycles(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES", "10",
        )
        s = StoreStability(
            store_id="x", cycle_count=5,
        )
        assert s.is_stable is False

    def test_unstable_when_any_incident(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES", "10",
        )
        s = StoreStability(
            store_id="x", cycle_count=50,
            cycle_errors=1,
        )
        assert s.is_stable is False


class TestCheckAutonomyGate:
    def test_no_stores_locked(self):
        with patch(
            "engines.autonomy_gate.threshold."
            "_list_active_stores",
            return_value=[],
        ):
            report = check_autonomy_gate()
        assert report.unlocked is False
        assert any(
            "no stores" in b for b in report.blockers
        )

    def test_fewer_stable_than_required(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_REQUIRED_STORES", "5",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES", "10",
        )
        with patch(
            "engines.autonomy_gate.threshold."
            "_list_active_stores",
            return_value=[
                "store_a", "store_b", "store_c",
            ],
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_cycle_history_per_store",
            return_value=(20, 0),
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_autopause_fires",
            return_value=0,
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_rejected_actions",
            return_value=0,
        ):
            report = check_autonomy_gate()
        # 3 stable stores < 5 required
        assert report.stable_count == 3
        assert report.unlocked is False
        assert any(
            "need" in b for b in report.blockers
        )

    def test_unlocked_when_5_stable(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_REQUIRED_STORES", "5",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES", "10",
        )
        with patch(
            "engines.autonomy_gate.threshold."
            "_list_active_stores",
            return_value=[
                f"store_{x}" for x in "abcdef"
            ],
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_cycle_history_per_store",
            return_value=(30, 0),
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_autopause_fires",
            return_value=0,
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_rejected_actions",
            return_value=0,
        ):
            report = check_autonomy_gate()
        assert report.stable_count == 6
        assert report.unlocked is True

    def test_one_incident_blocks_store(
        self, monkeypatch,
    ):
        """A single incident makes the store unstable."""
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_REQUIRED_STORES", "5",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_GATE_MIN_CYCLES", "10",
        )

        def fake_cycles(sid, **kwargs):
            return 20, 0

        def fake_autopause(sid, **kwargs):
            # store_a has 1 autopause fire
            return 1 if sid == "store_a" else 0

        with patch(
            "engines.autonomy_gate.threshold."
            "_list_active_stores",
            return_value=[
                f"store_{x}" for x in "abcde"
            ],
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_cycle_history_per_store",
            side_effect=fake_cycles,
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_autopause_fires",
            side_effect=fake_autopause,
        ), patch(
            "engines.autonomy_gate.threshold."
            "_safe_rejected_actions",
            return_value=0,
        ):
            report = check_autonomy_gate()
        # 4 stable (b,c,d,e) - store_a fails on
        # autopause
        assert report.stable_count == 4
        assert report.unlocked is False


class TestQuickCheck:
    def test_is_autonomy_unlocked_returns_bool(self):
        with patch(
            "engines.autonomy_gate.threshold."
            "_list_active_stores",
            return_value=[],
        ):
            assert is_autonomy_unlocked() is False

    def test_safe_fallback_on_raise(self):
        """If anything raises, return False (locked)."""
        with patch(
            "engines.autonomy_gate.threshold."
            "check_autonomy_gate",
            side_effect=RuntimeError("test"),
        ):
            assert is_autonomy_unlocked() is False


class TestEnvelope:
    def test_envelope_shape(self):
        with patch(
            "engines.autonomy_gate.threshold."
            "_list_active_stores",
            return_value=[],
        ):
            r = AutonomyGateEngine().run({})
        assert r["status"] == "success"
        assert r["meta"]["engine"] == "autonomy_gate"
        assert "unlocked" in r["data"]

    def test_non_dict_input_error(self):
        r = AutonomyGateEngine().run("nope")
        assert r["status"] == "error"
