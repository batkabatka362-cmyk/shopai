"""Tests for the auto-approve evaluator + persisted allowlist.

The evaluator decides whether a just-enqueued action should
short-circuit the manual review step. Four guardrails compose
with AND, and the safe default is no auto-approve unless the
engine has explicitly opted in via the persisted allowlist.

Coverage:
  - guardrails fire in correct order (allowlist → confidence →
    history → ratio)
  - config persistence is atomic + parse-safe
  - load_config fails open on missing / corrupt files
  - queue integration: maybe_auto_approve transitions PENDING →
    APPROVED with the right `decided_by` and decision_log row
  - pytest gate (Pattern J) prevents auto-approve under tests
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def auto_approve_data_dir(tmp_path: Path, monkeypatch):
    """Redirect the config path to a temp dir so tests don't
    touch the live data/ allowlist."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def queue(tmp_path: Path):
    from core.approval.queue import ApprovalQueue
    q = ApprovalQueue(db_path=tmp_path / "approval.db")
    yield q
    q._conn.close()


def _seed_outcomes(q, *, engine, positive, negative=0):
    """Helper: enqueue + approve + execute + record outcome N times."""
    for i in range(positive):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="", confidence=0.9,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={"revenue": 10}, source_event=f"p{i}",
        )
    for i in range(negative):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="", confidence=0.9,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="refunds/create", polarity="negative",
            metrics={"revenue": 5}, source_event=f"n{i}",
        )


# ─── Evaluator guardrails ──────────────────────────────────────


class TestEvaluatorGuardrails:

    def test_engine_not_in_allowlist_short_circuits(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        d = evaluate(
            engine="x", confidence=0.95, queue=queue,
            config=AutoApproveConfig(allowlist=frozenset()),
        )
        assert d.should_auto is False
        assert d.reason == "engine_not_in_allowlist"
        # Cheap short-circuit: outcome_ratio / total_outcomes never
        # fetched
        assert d.total_outcomes == 0

    def test_missing_confidence_fails(self, auto_approve_data_dir, queue):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        d = evaluate(
            engine="x", confidence=None, queue=queue,
            config=AutoApproveConfig(allowlist=frozenset({"x"})),
        )
        assert d.should_auto is False
        assert d.reason == "confidence_missing"

    def test_non_numeric_confidence_fails(self, auto_approve_data_dir, queue):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        d = evaluate(
            engine="x", confidence="high",  # type: ignore[arg-type]
            queue=queue,
            config=AutoApproveConfig(allowlist=frozenset({"x"})),
        )
        assert d.should_auto is False
        assert d.reason == "confidence_not_numeric"

    def test_low_confidence_fails(self, auto_approve_data_dir, queue):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        d = evaluate(
            engine="x", confidence=0.50, queue=queue,
            config=AutoApproveConfig(allowlist=frozenset({"x"})),
        )
        assert d.should_auto is False
        assert "confidence_below_threshold" in d.reason

    def test_insufficient_history_fails(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        _seed_outcomes(queue, engine="x", positive=5)
        d = evaluate(
            engine="x", confidence=0.95, queue=queue,
            config=AutoApproveConfig(allowlist=frozenset({"x"})),
        )
        assert d.should_auto is False
        assert "insufficient_history" in d.reason

    def test_low_outcome_ratio_fails(self, auto_approve_data_dir, queue):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        # 15 positive + 15 negative → ratio 0.5, well below threshold
        _seed_outcomes(queue, engine="x", positive=15, negative=15)
        d = evaluate(
            engine="x", confidence=0.95, queue=queue,
            config=AutoApproveConfig(allowlist=frozenset({"x"})),
        )
        assert d.should_auto is False
        assert "outcome_ratio_below_threshold" in d.reason

    def test_all_guardrails_pass(self, auto_approve_data_dir, queue):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        _seed_outcomes(queue, engine="x", positive=25, negative=2)
        d = evaluate(
            engine="x", confidence=0.95, queue=queue,
            config=AutoApproveConfig(allowlist=frozenset({"x"})),
        )
        assert d.should_auto is True
        assert "auto_threshold" in d.reason
        assert d.confidence == pytest.approx(0.95)
        # 25 positive / (25+2) ≈ 0.93
        assert d.outcome_ratio is not None
        assert d.outcome_ratio > 0.9

    def test_stats_lookup_failure_fails_safe(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import AutoApproveConfig, evaluate
        with patch.object(
            queue, "engine_outcome_stats",
            side_effect=RuntimeError("db lock"),
        ):
            d = evaluate(
                engine="x", confidence=0.95, queue=queue,
                config=AutoApproveConfig(allowlist=frozenset({"x"})),
            )
        assert d.should_auto is False
        assert d.reason == "outcome_stats_unavailable"


# --- Guardrail #5: engine_health verdict ---------------------


def _stub_health(verdict: str):
    """Minimal stand-in EngineHealth for guarding by verdict."""
    from core.approval.engine_health import EngineHealth
    return EngineHealth(
        engine="x", score=5, verdict=verdict,
        signals={}, concerns=[],
    )


class TestEngineHealthGuard:

    def test_unhealthy_blocks_auto_approve(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import (
            AutoApproveConfig, evaluate,
        )
        # Pass all 4 prior guards: allowlist + confidence +
        # 27 outcomes at high ratio.
        _seed_outcomes(queue, engine="x", positive=25, negative=2)
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_stub_health("unhealthy"),
        ):
            d = evaluate(
                engine="x", confidence=0.95, queue=queue,
                config=AutoApproveConfig(
                    allowlist=frozenset({"x"}),
                ),
            )
        assert d.should_auto is False
        assert d.reason == "engine_health_unhealthy"

    def test_warning_still_auto_approves(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import (
            AutoApproveConfig, evaluate,
        )
        _seed_outcomes(queue, engine="x", positive=25, negative=2)
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_stub_health("warning"),
        ):
            d = evaluate(
                engine="x", confidence=0.95, queue=queue,
                config=AutoApproveConfig(
                    allowlist=frozenset({"x"}),
                ),
            )
        # warning verdict alone shouldn't block; the existing
        # 4 guards already filter the worst cases.
        assert d.should_auto is True
        assert "auto_threshold" in d.reason

    def test_healthy_auto_approves(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import (
            AutoApproveConfig, evaluate,
        )
        _seed_outcomes(queue, engine="x", positive=25, negative=2)
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_stub_health("healthy"),
        ):
            d = evaluate(
                engine="x", confidence=0.95, queue=queue,
                config=AutoApproveConfig(
                    allowlist=frozenset({"x"}),
                ),
            )
        assert d.should_auto is True

    def test_health_probe_raise_fails_open(
        self, auto_approve_data_dir, queue,
    ):
        """A raising health scorer doesn't block more than the
        absence of the guard would. The 4 prior guards still
        decide."""
        from core.approval.auto_approve import (
            AutoApproveConfig, evaluate,
        )
        _seed_outcomes(queue, engine="x", positive=25, negative=2)
        with patch(
            "core.approval.engine_health.score_engine",
            side_effect=RuntimeError("scorer down"),
        ):
            d = evaluate(
                engine="x", confidence=0.95, queue=queue,
                config=AutoApproveConfig(
                    allowlist=frozenset({"x"}),
                ),
            )
        assert d.should_auto is True
        assert "auto_threshold" in d.reason

    def test_guard_runs_after_outcome_ratio(
        self, auto_approve_data_dir, queue,
    ):
        """When outcome_ratio FAILS, the failure reason should be
        the ratio one (not health) -- prior guards short-circuit."""
        from core.approval.auto_approve import (
            AutoApproveConfig, evaluate,
        )
        _seed_outcomes(queue, engine="x", positive=15, negative=15)
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_stub_health("unhealthy"),
        ):
            d = evaluate(
                engine="x", confidence=0.95, queue=queue,
                config=AutoApproveConfig(
                    allowlist=frozenset({"x"}),
                ),
            )
        # Ratio guard fires first.
        assert d.should_auto is False
        assert "outcome_ratio_below_threshold" in d.reason


# ─── Config persistence ────────────────────────────────────────


class TestConfigPersistence:

    def test_load_missing_file_returns_empty(
        self, auto_approve_data_dir,
    ):
        from core.approval.auto_approve import load_config
        cfg = load_config()
        assert cfg.allowlist == frozenset()

    def test_load_corrupt_file_returns_empty(
        self, auto_approve_data_dir,
    ):
        from core.approval.auto_approve import load_config
        (auto_approve_data_dir / "auto_approve_config.json").write_text(
            "this is not json {{{{",
        )
        cfg = load_config()
        assert cfg.allowlist == frozenset()

    def test_save_and_reload_roundtrip(self, auto_approve_data_dir):
        from core.approval.auto_approve import (
            AutoApproveConfig, load_config, save_config,
        )
        save_config(AutoApproveConfig(allowlist=frozenset({"x", "y"})))
        loaded = load_config()
        assert loaded.allowlist == frozenset({"x", "y"})

    def test_enable_engine_persists(self, auto_approve_data_dir):
        from core.approval.auto_approve import enable_engine, load_config
        new = enable_engine("cart_recovery")
        assert "cart_recovery" in new.allowlist
        # Re-reading the file matches the in-memory result
        assert load_config().allowlist == new.allowlist

    def test_disable_engine_persists(self, auto_approve_data_dir):
        from core.approval.auto_approve import (
            AutoApproveConfig, disable_engine, save_config,
        )
        save_config(
            AutoApproveConfig(allowlist=frozenset({"a", "b"})),
        )
        new = disable_engine("a")
        assert "a" not in new.allowlist
        assert "b" in new.allowlist

    def test_enable_empty_engine_raises(self, auto_approve_data_dir):
        from core.approval.auto_approve import enable_engine
        with pytest.raises(ValueError):
            enable_engine("")

    def test_persisted_file_is_valid_json(self, auto_approve_data_dir):
        from core.approval.auto_approve import (
            AutoApproveConfig, save_config,
        )
        save_config(AutoApproveConfig(allowlist=frozenset({"a"})))
        path = auto_approve_data_dir / "auto_approve_config.json"
        assert path.exists()
        # Re-parse via plain json to confirm it's not pickled or
        # binary
        data = json.loads(path.read_text())
        assert data == {"allowlist": ["a"]}


# ─── Queue integration ─────────────────────────────────────────


class TestQueueIntegration:

    def test_enqueue_returns_pending_under_pytest_gate(
        self, auto_approve_data_dir, queue,
    ):
        """Pattern J guard: even with a perfect outcome history +
        allowlist, the evaluator must not auto-approve under
        pytest. Tests that exercise the integration patch
        _is_test_environment to lift the gate."""
        from core.approval.auto_approve import enable_engine
        enable_engine("x")
        _seed_outcomes(queue, engine="x", positive=25)
        # Sanity: history seeded
        assert queue.engine_outcome_stats("x")["positive_count"] >= 25

        a = queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="", confidence=0.95,
        )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING

    def test_with_gate_lifted_auto_approves(
        self, auto_approve_data_dir, queue,
    ):
        """When the pytest gate is patched, auto-approve fires for
        engines that clear all four guardrails."""
        from core.approval.auto_approve import enable_engine
        enable_engine("x")
        _seed_outcomes(queue, engine="x", positive=25)

        with patch(
            "core.approval.auto_approve._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="", confidence=0.95,
            )

        # Refreshed action reflects the auto-transition
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.APPROVED
        assert a.decided_by == "auto_threshold"
        assert a.decision_reason is not None
        assert "auto_threshold" in a.decision_reason

    def test_auto_approve_writes_decision_log_row(
        self, auto_approve_data_dir, queue,
    ):
        """The decision_log audit trail must include auto-approvals
        — operators inspecting the trail need to see what fired
        the transition, not just that it happened."""
        from core.approval.auto_approve import enable_engine
        enable_engine("x")
        _seed_outcomes(queue, engine="x", positive=25)

        with patch(
            "core.approval.auto_approve._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="", confidence=0.95,
            )

        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 1
        assert rows[0]["decision"] == "approved"
        assert rows[0]["decided_by"] == "auto_threshold"
        assert "auto_threshold" in (rows[0]["reason"] or "")

    def test_disabled_engine_stays_pending(
        self, auto_approve_data_dir, queue,
    ):
        """Engine not in allowlist → no auto-approve even with
        perfect history + confidence (and gate lifted)."""
        _seed_outcomes(queue, engine="x", positive=25)
        with patch(
            "core.approval.auto_approve._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="", confidence=0.95,
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING

    def test_low_confidence_stays_pending(
        self, auto_approve_data_dir, queue,
    ):
        from core.approval.auto_approve import enable_engine
        enable_engine("x")
        _seed_outcomes(queue, engine="x", positive=25)
        with patch(
            "core.approval.auto_approve._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="", confidence=0.5,
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING
