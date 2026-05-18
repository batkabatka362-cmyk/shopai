"""Tests for ``shopai engine alerts`` — degradation detector
that flags engines whose recent outcome score has dropped
versus a longer baseline window.

Verifies:

  - Argument validation: baseline must exceed recent
  - Empty queue → friendly empty state
  - Engines with insufficient signal (below --min-recent) are
    surveyed but never alerted
  - Score drop ≥ threshold triggers an alert
  - Score drop < threshold doesn't alert
  - Ranking: largest drop first
  - JSON envelope shape
  - Resilience: queue scan failure, get_outcomes raise
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        recent_hours=24, baseline_hours=168,
        threshold=0.2, min_recent=3,
        per_store=False, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _row(*, id_, engine, decided_at):
    return {
        "id": id_,
        "engine": engine,
        "decided_at": decided_at,
    }


def _fake_queue(*, rows=None, outcomes=None, scan_raises=None):
    rows = rows or []
    outcomes = outcomes or {}
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    # Pre-compute distinct engines for the COUNT(DISTINCT) path.
    distinct_engines = len({r.get("engine", "?") for r in rows})
    if scan_raises is not None:
        fake_conn.execute.side_effect = scan_raises
    else:
        def _execute(sql, params=()):
            cursor = MagicMock()
            # Detect the engine_count COUNT query: it asks for
            # ``COUNT(DISTINCT engine)``. Everything else uses
            # the rows-via-fetchall path.
            if "COUNT(DISTINCT engine)" in sql:
                count_row = {"n": distinct_engines}
                cursor.fetchone.return_value = count_row
            else:
                cursor.fetchall.return_value = rows
            return cursor
        fake_conn.execute.side_effect = _execute
    q._conn = fake_conn
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


# ─── Argument validation ─────────────────────────────────────


class TestArgValidation:

    def test_baseline_must_exceed_recent(self, cli):
        out, code = _capture(
            cli._cmd_engine_alerts,
            _ns(recent_hours=48, baseline_hours=48),
        )
        assert code == 1
        assert "must exceed" in out

    def test_baseline_lower_than_recent_fails(self, cli):
        out, code = _capture(
            cli._cmd_engine_alerts,
            _ns(recent_hours=72, baseline_hours=48),
        )
        assert code == 1
        assert "must exceed" in out


# ─── Empty state ─────────────────────────────────────────────


class TestEmptyState:

    def test_no_activity_returns_friendly_message(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, code = _capture(
                cli._cmd_engine_alerts, _ns(),
            )
        assert code == 0
        assert "No engine activity" in out

    def test_empty_json_envelope(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        data = json.loads(out)
        assert data["alert_count"] == 0
        assert data["engine_count"] == 0
        assert data["alerts"] == []


# ─── Alert triggers ──────────────────────────────────────────


class TestAlertTriggers:

    def test_degradation_above_threshold_alerts(self, cli):
        """Recent: 0/4 polarised → score 0. Baseline: 8/12
        polarised → score 0.67. Drop 0.67, threshold 0.2 → alert."""
        now = time.time()
        recent_ts = now - 3600.0  # 1h ago, in 24h recent
        old_ts = now - 100 * 3600.0  # 100h ago, in baseline only

        rows = [
            _row(id_=f"r{i}", engine="loyalty",
                 decided_at=recent_ts)
            for i in range(4)
        ] + [
            _row(id_=f"o{i}", engine="loyalty",
                 decided_at=old_ts)
            for i in range(8)
        ]
        outcomes = {}
        # Recent rows all NEGATIVE.
        for i in range(4):
            outcomes[f"r{i}"] = [
                {"polarity": "negative", "metrics": {}},
            ]
        # Older rows all POSITIVE.
        for i in range(8):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]

        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, code = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["alert_count"] == 1
        alert = data["alerts"][0]
        assert alert["engine"] == "loyalty"
        # Recent score 0; baseline score = 8 / 12 ≈ 0.67.
        assert alert["recent_score"] == 0.0
        assert alert["baseline_score"] == pytest.approx(8 / 12)
        assert alert["drop"] == pytest.approx(8 / 12)

    def test_below_threshold_no_alert(self, cli):
        """Recent 2 pos / 3 polarised = 0.67. Baseline 8 pos /
        9 polarised = 0.89. Drop 0.22 -- but with threshold 0.3
        no alert."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = (
            [_row(id_=f"r{i}", engine="loyalty",
                  decided_at=recent_ts) for i in range(3)]
            + [_row(id_=f"o{i}", engine="loyalty",
                    decided_at=old_ts) for i in range(6)]
        )
        outcomes = {
            "r0": [{"polarity": "positive", "metrics": {}}],
            "r1": [{"polarity": "positive", "metrics": {}}],
            "r2": [{"polarity": "negative", "metrics": {}}],
        }
        for i in range(6):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts,
                _ns(threshold=0.3, json=True),
            )
        data = json.loads(out)
        assert data["alert_count"] == 0

    def test_insufficient_recent_signal_no_alert(self, cli):
        """Recent has only 2 polarised events (below --min-recent
        of 3). Even with a dramatic score drop, no alert -- the
        signal is too noisy to trust."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = (
            [_row(id_=f"r{i}", engine="loyalty",
                  decided_at=recent_ts) for i in range(2)]
            + [_row(id_=f"o{i}", engine="loyalty",
                    decided_at=old_ts) for i in range(10)]
        )
        outcomes = {
            "r0": [{"polarity": "negative", "metrics": {}}],
            "r1": [{"polarity": "negative", "metrics": {}}],
        }
        for i in range(10):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        data = json.loads(out)
        assert data["alert_count"] == 0


# ─── Ranking ─────────────────────────────────────────────────


class TestRanking:

    def test_largest_drop_first(self, cli):
        """Two engines both flagged; the one with larger drop
        ranks first.

        engineA: all-positive baseline (12 pos), all-negative
        recent (4 neg). Recent score 0, baseline score 8/12 ≈
        0.67, drop ≈ 0.67.
        engineB: 2 pos + 2 neg recent (score 0.5), all-positive
        older + the 2 pos recent in baseline (10 pos + 2 neg →
        score 10/12 ≈ 0.83). Drop ≈ 0.33.
        Threshold 0.2 → both flagged; A ranks first."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = []
        outcomes = {}
        # engineA: 4 recent (all negative) + 8 older (all positive)
        for i in range(4):
            rows.append(_row(
                id_=f"a_r{i}", engine="engineA",
                decided_at=recent_ts,
            ))
            outcomes[f"a_r{i}"] = [
                {"polarity": "negative", "metrics": {}},
            ]
        for i in range(8):
            rows.append(_row(
                id_=f"a_o{i}", engine="engineA",
                decided_at=old_ts,
            ))
            outcomes[f"a_o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        # engineB: 4 recent (2 pos + 2 neg) + 8 older (all pos)
        for i in range(4):
            rows.append(_row(
                id_=f"b_r{i}", engine="engineB",
                decided_at=recent_ts,
            ))
            outcomes[f"b_r{i}"] = [
                {"polarity": "positive" if i < 2 else "negative",
                 "metrics": {}},
            ]
        for i in range(8):
            rows.append(_row(
                id_=f"b_o{i}", engine="engineB",
                decided_at=old_ts,
            ))
            outcomes[f"b_o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]

        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        data = json.loads(out)
        assert data["alert_count"] == 2
        # engineA (~0.67 drop) ranks before engineB (~0.33 drop).
        assert data["alerts"][0]["engine"] == "engineA"
        assert data["alerts"][1]["engine"] == "engineB"


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_scan_failure_surfaces_error(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                scan_raises=RuntimeError("db locked"),
            ),
        ):
            out, code = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "db locked" in data["error"]

    def test_get_outcomes_raise_treated_as_empty(self, cli):
        """get_outcomes raising on one action shouldn't crash
        the run; that action simply contributes no polarity."""
        now = time.time()
        rows = [
            _row(id_="x", engine="loyalty",
                 decided_at=now - 3600.0),
        ]
        q = _fake_queue(rows=rows)
        q.get_outcomes.side_effect = RuntimeError(
            "outcomes table missing",
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        # No alert -- no polarised signal -- but no crash either.
        assert data["alert_count"] == 0
        assert data["engine_count"] == 1


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_carries_thresholds(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts,
                _ns(
                    recent_hours=48, baseline_hours=336,
                    threshold=0.25, min_recent=5,
                    json=True,
                ),
            )
        data = json.loads(out)
        assert data["recent_hours"] == 48
        assert data["baseline_hours"] == 336
        assert data["threshold"] == 0.25
        assert data["min_recent"] == 5


# ─── Quarantine flags ────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


def _seed_degradation(engine, *, recent_neg=4, baseline_pos=8):
    """Helper: build a fake queue with rows + outcomes that
    produce a clear degradation alert for ``engine``."""
    now = time.time()
    recent_ts = now - 3600.0
    old_ts = now - 100 * 3600.0
    rows = [
        _row(id_=f"r{i}", engine=engine, decided_at=recent_ts)
        for i in range(recent_neg)
    ] + [
        _row(id_=f"o{i}", engine=engine, decided_at=old_ts)
        for i in range(baseline_pos)
    ]
    outcomes = {}
    for i in range(recent_neg):
        outcomes[f"r{i}"] = [
            {"polarity": "negative", "metrics": {}},
        ]
    for i in range(baseline_pos):
        outcomes[f"o{i}"] = [
            {"polarity": "positive", "metrics": {}},
        ]
    return rows, outcomes


class TestQuarantineFlags:
    """Each alert row gets a ``flags`` list so operators can
    de-prioritise alerts on engines that are already paused."""

    def test_clean_engine_empty_flags(self, cli, data_dir):
        rows, outcomes = _seed_degradation("loyalty")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        data = json.loads(out)
        assert data["alerts"][0]["flags"] == []

    def test_alert_paused_engine_flagged(
        self, cli, data_dir,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        rows, outcomes = _seed_degradation("loyalty")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        data = json.loads(out)
        assert data["alerts"][0]["flags"] == ["alert_paused"]

    def test_text_render_includes_flags(self, cli, data_dir):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        rows, outcomes = _seed_degradation("loyalty")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(cli._cmd_engine_alerts, _ns())
        assert "alert_paused" in out

    def test_load_state_failure_empty_flags(
        self, cli, data_dir,
    ):
        rows, outcomes = _seed_degradation("loyalty")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ), patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            out, code = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["alerts"][0]["flags"] == []


# ─── --per-store flag ────────────────────────────────────────


class TestPerStoreFlag:
    """``--per-store`` switches to
    ``compute_engine_alerts_per_store`` which produces
    (engine, store_id) alerts."""

    def _per_store_alerts(self, *, with_store=True):
        from core.approval.outcome_trends import EngineAlert
        return [
            EngineAlert(
                engine="loyalty",
                store_id=("store_a" if with_store else None),
                recent_executed=5,
                baseline_executed=20,
                recent_score=0.2,
                baseline_score=0.85,
                recent_polarised=5,
                baseline_polarised=18,
                drop=0.65,
                detail=(
                    "20% recent vs 85% baseline (drop 65%)"
                    + ("@store_a" if with_store else " (fleet)")
                ),
            ),
        ]

    def test_per_store_dispatch(self, cli):
        """--per-store calls compute_engine_alerts_per_store."""
        with patch(
            "core.approval.outcome_trends."
            "compute_engine_alerts_per_store",
            return_value=self._per_store_alerts(),
        ) as per_store_mock, patch(
            "core.approval.outcome_trends.compute_engine_alerts",
        ) as fleet_mock, patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts,
                _ns(per_store=True, json=True),
            )
        per_store_mock.assert_called_once()
        fleet_mock.assert_not_called()
        data = json.loads(out)
        assert data["per_store"] is True
        assert data["alerts"][0]["store_id"] == "store_a"

    def test_default_dispatch_unchanged(self, cli):
        """Without --per-store, fleet-wide compute is called."""
        with patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[],
        ) as fleet_mock, patch(
            "core.approval.outcome_trends."
            "compute_engine_alerts_per_store",
        ) as per_store_mock, patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        fleet_mock.assert_called_once()
        per_store_mock.assert_not_called()
        data = json.loads(out)
        assert data["per_store"] is False

    def test_text_render_includes_store_label(self, cli):
        with patch(
            "core.approval.outcome_trends."
            "compute_engine_alerts_per_store",
            return_value=self._per_store_alerts(),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts,
                _ns(per_store=True),
            )
        assert "(per-store)" in out
        assert "loyalty@store_a" in out

    def test_text_render_omits_label_for_fleet_alert(
        self, cli,
    ):
        """Per-store mode can also produce fleet-bucketed
        alerts (None store_id). They render without
        ``@store_id`` suffix."""
        with patch(
            "core.approval.outcome_trends."
            "compute_engine_alerts_per_store",
            return_value=self._per_store_alerts(with_store=False),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts,
                _ns(per_store=True),
            )
        # No @ suffix
        assert "loyalty@" not in out
        assert "loyalty" in out

    def test_per_store_envelope_has_store_id_field(
        self, cli,
    ):
        """JSON envelope's alerts entries always carry
        store_id field (None for fleet-bucketed)."""
        with patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=self._per_store_alerts(
                with_store=False,
            ),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_alerts, _ns(json=True),
            )
        data = json.loads(out)
        # Even fleet-mode alerts have store_id field (None)
        assert "store_id" in data["alerts"][0]
