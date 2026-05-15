"""Tests for the failed-engine quarantine evaluator + persisted state.

The evaluator decides whether a just-enqueued action's engine
should be auto-paused (rejected) due to a predominantly negative
outcome history. Guardrails compose with AND, and the safe
defaults make quarantine fire only when the signal is reliable
(≥ 20 polarised outcomes) and severe (≥ 50% negative).

Coverage:
  - all guardrails fire in order (exempt → released → stats →
    history → ratio)
  - state persistence (exemptions + released lists)
  - load_state fails open on missing / corrupt files
  - queue integration: maybe_quarantine transitions PENDING →
    REJECTED with `decided_by="auto_quarantine"` and writes a
    decision_log row
  - pytest gate (Pattern J) prevents quarantine under tests
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def quarantine_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def queue(tmp_path: Path):
    from core.approval.queue import ApprovalQueue
    q = ApprovalQueue(db_path=tmp_path / "approval.db")
    yield q
    q._conn.close()


def _seed(q, *, engine, positive, negative=0):
    for i in range(positive):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={}, source_event=f"p{engine}_{i}",
        )
    for i in range(negative):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="refunds/create", polarity="negative",
            metrics={}, source_event=f"n{engine}_{i}",
        )


# ─── Evaluator guardrails ──────────────────────────────────────


class TestEvaluatorGuardrails:

    def test_exempt_engine_short_circuits(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import QuarantineState, evaluate
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset({"x"}),
                released=frozenset(),
            ),
        )
        assert d.should_quarantine is False
        assert d.reason == "engine_exempt"

    def test_released_engine_short_circuits(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import QuarantineState, evaluate
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset(),
                released=frozenset({"x"}),
            ),
        )
        assert d.should_quarantine is False
        assert d.reason == "engine_released_by_operator"

    def test_insufficient_history(self, quarantine_data_dir, queue):
        from core.approval.quarantine import QuarantineState, evaluate
        # 3 negative, 0 positive — bad ratio but below floor
        _seed(queue, engine="x", positive=0, negative=3)
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset(), released=frozenset(),
            ),
        )
        assert d.should_quarantine is False
        assert "insufficient_history" in d.reason

    def test_healthy_ratio_no_quarantine(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import QuarantineState, evaluate
        _seed(queue, engine="x", positive=18, negative=2)
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset(), released=frozenset(),
            ),
        )
        assert d.should_quarantine is False
        assert "healthy" in d.reason
        # 2/20 = 0.10, well below 0.50 threshold
        assert d.negative_ratio is not None
        assert d.negative_ratio < 0.2

    def test_bad_ratio_quarantines(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import QuarantineState, evaluate
        _seed(queue, engine="x", positive=5, negative=25)
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset(), released=frozenset(),
            ),
        )
        assert d.should_quarantine is True
        assert "auto_quarantine" in d.reason
        assert d.negative_ratio is not None
        assert d.negative_ratio > 0.8

    def test_borderline_ratio_no_quarantine(
        self, quarantine_data_dir, queue,
    ):
        """49% negative is below the 50% threshold — quarantine
        doesn't fire on a hair-trigger."""
        from core.approval.quarantine import QuarantineState, evaluate
        # 51 positive + 49 negative → exactly 49% negative
        _seed(queue, engine="x", positive=51, negative=49)
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset(), released=frozenset(),
            ),
        )
        assert d.should_quarantine is False

    def test_stats_lookup_failure_fails_safe(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import QuarantineState, evaluate
        with patch.object(
            queue, "engine_outcome_stats",
            side_effect=RuntimeError("db lock"),
        ):
            d = evaluate(
                engine="x", queue=queue,
                state=QuarantineState(
                    exemptions=frozenset(),
                    released=frozenset(),
                ),
            )
        assert d.should_quarantine is False
        assert d.reason == "outcome_stats_unavailable"

    def test_exempt_takes_priority_over_bad_ratio(
        self, quarantine_data_dir, queue,
    ):
        """An exempted engine STAYS exempt even with a terrible
        ratio. This is the legit-negative-polarity engine case
        (returns workflow, etc.)."""
        from core.approval.quarantine import QuarantineState, evaluate
        _seed(queue, engine="x", positive=2, negative=28)
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset({"x"}),
                released=frozenset(),
            ),
        )
        assert d.should_quarantine is False
        assert d.reason == "engine_exempt"

    def test_released_takes_priority_over_bad_ratio(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import QuarantineState, evaluate
        _seed(queue, engine="x", positive=2, negative=28)
        d = evaluate(
            engine="x", queue=queue,
            state=QuarantineState(
                exemptions=frozenset(),
                released=frozenset({"x"}),
            ),
        )
        assert d.should_quarantine is False
        assert d.reason == "engine_released_by_operator"


# ─── State persistence ─────────────────────────────────────────


class TestStatePersistence:

    def test_load_missing_returns_empty(self, quarantine_data_dir):
        from core.approval.quarantine import load_state
        s = load_state()
        assert s.exemptions == frozenset()
        assert s.released == frozenset()

    def test_load_corrupt_fails_open(self, quarantine_data_dir):
        from core.approval.quarantine import load_state
        (quarantine_data_dir / "quarantine_state.json").write_text(
            "not valid json {{{",
        )
        s = load_state()
        assert s.exemptions == frozenset()
        assert s.released == frozenset()

    def test_exempt_engine_persists(self, quarantine_data_dir):
        from core.approval.quarantine import (
            exempt_engine, load_state,
        )
        exempt_engine("returns")
        s = load_state()
        assert "returns" in s.exemptions

    def test_unexempt_removes(self, quarantine_data_dir):
        from core.approval.quarantine import (
            exempt_engine, load_state, unexempt_engine,
        )
        exempt_engine("a")
        exempt_engine("b")
        unexempt_engine("a")
        s = load_state()
        assert "a" not in s.exemptions
        assert "b" in s.exemptions

    def test_release_and_clear_release_roundtrip(
        self, quarantine_data_dir,
    ):
        from core.approval.quarantine import (
            clear_release, load_state, release_engine,
        )
        release_engine("loyalty")
        assert "loyalty" in load_state().released
        clear_release("loyalty")
        assert "loyalty" not in load_state().released

    def test_release_doesnt_touch_exemptions(
        self, quarantine_data_dir,
    ):
        """Releasing engine X must not affect existing
        exemptions for engine Y."""
        from core.approval.quarantine import (
            exempt_engine, load_state, release_engine,
        )
        exempt_engine("y")
        release_engine("x")
        s = load_state()
        assert "y" in s.exemptions
        assert "x" in s.released

    def test_empty_name_raises(self, quarantine_data_dir):
        from core.approval.quarantine import (
            exempt_engine, release_engine,
        )
        with pytest.raises(ValueError):
            exempt_engine("")
        with pytest.raises(ValueError):
            release_engine("")

    def test_persisted_file_is_valid_json(self, quarantine_data_dir):
        from core.approval.quarantine import (
            exempt_engine, release_engine,
        )
        exempt_engine("a")
        release_engine("b")
        path = quarantine_data_dir / "quarantine_state.json"
        data = json.loads(path.read_text())
        assert data == {
            "exemptions": ["a"], "released": ["b"],
        }


# ─── Queue integration ─────────────────────────────────────────


class TestQueueIntegration:

    def test_pytest_gate_prevents_quarantine(
        self, quarantine_data_dir, queue,
    ):
        """With bad-ratio history seeded, the pytest gate
        prevents the live auto-reject so tests don't trip on
        their own fixtures."""
        _seed(queue, engine="x", positive=5, negative=25)
        a = queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING

    def test_gate_lifted_quarantines(
        self, quarantine_data_dir, queue,
    ):
        _seed(queue, engine="x", positive=5, negative=25)
        with patch(
            "core.approval.quarantine._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="",
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.REJECTED
        assert a.decided_by == "auto_quarantine"
        assert a.decision_reason is not None
        assert "auto_quarantine" in a.decision_reason

    def test_quarantine_writes_decision_log_row(
        self, quarantine_data_dir, queue,
    ):
        _seed(queue, engine="x", positive=5, negative=25)
        with patch(
            "core.approval.quarantine._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="",
            )
        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 1
        assert rows[0]["decision"] == "rejected"
        assert rows[0]["decided_by"] == "auto_quarantine"
        assert "auto_quarantine" in (rows[0]["reason"] or "")

    def test_healthy_engine_stays_pending(
        self, quarantine_data_dir, queue,
    ):
        _seed(queue, engine="x", positive=25, negative=2)
        with patch(
            "core.approval.quarantine._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="",
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING

    def test_exempt_engine_bypasses_quarantine(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import exempt_engine
        _seed(queue, engine="x", positive=2, negative=28)
        exempt_engine("x")
        with patch(
            "core.approval.quarantine._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="",
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING

    def test_released_engine_bypasses_quarantine(
        self, quarantine_data_dir, queue,
    ):
        from core.approval.quarantine import release_engine
        _seed(queue, engine="x", positive=2, negative=28)
        release_engine("x")
        with patch(
            "core.approval.quarantine._is_test_environment",
            return_value=False,
        ):
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="",
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.PENDING


# ─── Interaction with auto-approve ─────────────────────────────


class TestAutoApproveInteraction:

    def test_auto_approve_skips_quarantine_check(
        self, quarantine_data_dir, queue,
    ):
        """When auto-approve fires (engine is healthy + on
        allowlist + high confidence), the quarantine hook is
        skipped — the engine just APPROVED was certified healthy
        moments ago, re-evaluating would be redundant work."""
        from core.approval.auto_approve import enable_engine
        _seed(queue, engine="x", positive=25)
        enable_engine("x")
        # Patch both gates simultaneously to lift them under
        # pytest
        with patch(
            "core.approval.auto_approve._is_test_environment",
            return_value=False,
        ), patch(
            "core.approval.quarantine._is_test_environment",
            return_value=False,
        ) as mock_q_gate:
            a = queue.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="", confidence=0.95,
            )
        from core.approval.queue import ApprovalStatus
        assert a.status == ApprovalStatus.APPROVED
        # Quarantine gate was never CALLED — the auto-approve
        # branch short-circuited the enqueue path before reaching
        # quarantine. (We check via the absence of any call: the
        # mock would still register if invoked.)
        # NOTE: this only verifies the gate function isn't called;
        # the underlying maybe_quarantine import side has its own
        # pytest gate fallback.
        assert mock_q_gate.called is False
