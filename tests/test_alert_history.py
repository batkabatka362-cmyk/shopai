"""Tests for ``core.approval.alert_history`` — persistent
alert-firing history.

Covers:
  - ``AlertEvent`` is a frozen dataclass with the expected fields
  - ``record_alerts`` appends to the JSON store; Pattern J guard
    prevents writes under pytest (autouse fixture re-enables it
    for this file)
  - ``recent_history`` filters + sorts newest-first
  - ``consecutive_runs_per_engine`` buckets multi-alerts-per-day
    as ONE bucket and counts buckets per engine
  - ``clear`` resets state
  - Fail-open semantics: missing / corrupt file returns ``[]``
  - ``SHOPAI_DATA_DIR`` env-var honored
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """Pattern J guard is on under pytest; this file's whole
    point is exercising the recorder, so flip it off."""
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def alert_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@dataclass
class _FakeAlert:
    engine: str
    drop: float = 0.3
    recent_score: float = 0.4
    baseline_score: float = 0.7


def test_alert_event_is_frozen():
    from core.approval.alert_history import AlertEvent
    e = AlertEvent(
        engine="loyalty", recorded_at=100.0, drop=0.3,
        recent_score=0.4, baseline_score=0.7,
    )
    with pytest.raises((AttributeError, Exception)):
        e.engine = "different"  # type: ignore[misc]


def test_record_alerts_appends_events(alert_data_dir: Path):
    from core.approval.alert_history import record_alerts

    n = record_alerts(
        [_FakeAlert("loyalty"), _FakeAlert("affiliate")],
        now=1000.0,
    )
    assert n == 2

    path = alert_data_dir / "alert_history.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    engines = sorted(e["engine"] for e in data)
    assert engines == ["affiliate", "loyalty"]
    assert all(e["recorded_at"] == 1000.0 for e in data)


def test_record_alerts_preserves_prior_history(alert_data_dir: Path):
    from core.approval.alert_history import record_alerts

    record_alerts([_FakeAlert("loyalty")], now=1000.0)
    record_alerts([_FakeAlert("affiliate")], now=2000.0)

    data = json.loads(
        (alert_data_dir / "alert_history.json").read_text(encoding="utf-8")
    )
    assert len(data) == 2


def test_record_alerts_skips_empty_engine(alert_data_dir: Path):
    from core.approval.alert_history import record_alerts

    n = record_alerts([_FakeAlert(""), _FakeAlert("   ")], now=1000.0)
    assert n == 0
    assert not (alert_data_dir / "alert_history.json").exists()


def test_record_alerts_pytest_guard_no_write(alert_data_dir: Path):
    """Pattern J — when the guard is ON (default under pytest),
    record_alerts returns 0 without persisting."""
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=True,
    ):
        from core.approval.alert_history import record_alerts
        n = record_alerts([_FakeAlert("loyalty")], now=1000.0)
    assert n == 0
    assert not (alert_data_dir / "alert_history.json").exists()


def test_recent_history_filters_by_window_and_sorts(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, recent_history,
    )

    # Three events at t=100, t=1000, t=2000
    record_alerts([_FakeAlert("a")], now=100.0)
    record_alerts([_FakeAlert("b")], now=1000.0)
    record_alerts([_FakeAlert("c")], now=2000.0)

    # Window covers the last 1500s from now=2500 → t>=1000
    out = recent_history(since_seconds=1500.0, now=2500.0)
    engines = [e.engine for e in out]
    assert engines == ["c", "b"]  # newest first


def test_recent_history_empty_when_no_file(alert_data_dir: Path):
    from core.approval.alert_history import recent_history
    assert recent_history(now=1000.0) == []


def test_recent_history_fails_open_on_corrupt(alert_data_dir: Path):
    from core.approval.alert_history import recent_history
    (alert_data_dir / "alert_history.json").write_text(
        "{not valid json", encoding="utf-8",
    )
    assert recent_history(now=1000.0) == []


def test_recent_history_fails_open_on_wrong_shape(alert_data_dir: Path):
    from core.approval.alert_history import recent_history
    (alert_data_dir / "alert_history.json").write_text(
        json.dumps({"not": "a list"}), encoding="utf-8",
    )
    assert recent_history(now=1000.0) == []


def test_consecutive_runs_buckets_same_day_as_one(alert_data_dir: Path):
    """Multiple alerts in the same bucket count as ONE — a
    daily-brief firing twice on the same day shouldn't inflate
    the consecutive-day count."""
    from core.approval.alert_history import (
        record_alerts, consecutive_runs_per_engine,
    )

    day = 86400.0
    # Three alerts on day-0, all the same engine
    record_alerts([_FakeAlert("loyalty")], now=10.0)
    record_alerts([_FakeAlert("loyalty")], now=100.0)
    record_alerts([_FakeAlert("loyalty")], now=200.0)

    out = consecutive_runs_per_engine(
        window_seconds=day * 7, bucket_seconds=day, now=day,
    )
    assert out == {"loyalty": 1}


def test_consecutive_runs_counts_distinct_buckets(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, consecutive_runs_per_engine,
    )

    day = 86400.0
    # Three alerts on three different days
    record_alerts([_FakeAlert("loyalty")], now=day * 0 + 1)
    record_alerts([_FakeAlert("loyalty")], now=day * 1 + 1)
    record_alerts([_FakeAlert("loyalty")], now=day * 2 + 1)

    out = consecutive_runs_per_engine(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 3,
    )
    assert out == {"loyalty": 3}


def test_consecutive_runs_excludes_outside_window(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, consecutive_runs_per_engine,
    )

    day = 86400.0
    # Old alert (8 days back) + recent alert (today)
    record_alerts([_FakeAlert("loyalty")], now=day * 0)
    record_alerts([_FakeAlert("loyalty")], now=day * 8 - 100.0)

    out = consecutive_runs_per_engine(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 8,
    )
    # Old event is outside the 7-day window; only recent counts
    assert out == {"loyalty": 1}


def test_consecutive_runs_per_engine_independence(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, consecutive_runs_per_engine,
    )

    day = 86400.0
    record_alerts([_FakeAlert("loyalty")], now=day * 0 + 1)
    record_alerts([_FakeAlert("loyalty")], now=day * 1 + 1)
    record_alerts([_FakeAlert("affiliate")], now=day * 2 + 1)

    out = consecutive_runs_per_engine(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 3,
    )
    assert out == {"loyalty": 2, "affiliate": 1}


def test_consecutive_runs_empty_when_no_history(alert_data_dir: Path):
    from core.approval.alert_history import consecutive_runs_per_engine
    assert consecutive_runs_per_engine(now=1000.0) == {}


def test_clear_wipes_history(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, recent_history, clear,
    )

    record_alerts([_FakeAlert("loyalty")], now=1000.0)
    assert len(recent_history(now=2000.0)) == 1

    clear()
    assert recent_history(now=2000.0) == []


def test_state_path_honors_shopai_data_dir(
    alert_data_dir: Path, monkeypatch
):
    """The env-var override is the same pattern used by
    quarantine.py — tests rely on it to isolate per-test state."""
    from core.approval.alert_history import _state_path
    assert _state_path() == alert_data_dir / "alert_history.json"


def test_load_raw_events_skips_malformed_entries(
    alert_data_dir: Path,
):
    """Entries missing required fields are skipped; the rest
    load."""
    from core.approval.alert_history import (
        recent_history,
    )

    payload = [
        {"engine": "good", "recorded_at": 1000.0, "drop": 0.3,
         "recent_score": 0.4, "baseline_score": 0.7},
        {"engine": "missing_recorded_at"},  # malformed
        "not a dict",  # malformed
        {"engine": "bad_type", "recorded_at": "not a float"},
    ]
    (alert_data_dir / "alert_history.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )

    out = recent_history(since_seconds=86400.0, now=2000.0)
    assert len(out) == 1
    assert out[0].engine == "good"


def test_prune_removes_old_events(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, prune, recent_history,
    )
    day = 86400.0
    record_alerts([_FakeAlert("a")], now=100.0)
    record_alerts([_FakeAlert("b")], now=day * 5)
    record_alerts([_FakeAlert("c")], now=day * 30)
    # Now = day*40, prune anything older than 20 days
    # -> drop a (40d), b (35d); keep c (10d)
    removed = prune(
        older_than_seconds=day * 20, now=day * 40,
    )
    assert removed == 2
    out = recent_history(since_seconds=day * 50, now=day * 40)
    assert [e.engine for e in out] == ["c"]


def test_prune_zero_removed_keeps_all(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, prune, recent_history,
    )
    record_alerts([_FakeAlert("fresh")], now=1000.0)
    removed = prune(older_than_seconds=86400.0, now=1100.0)
    assert removed == 0
    assert len(recent_history(now=1100.0)) == 1


def test_prune_negative_raises(alert_data_dir: Path):
    from core.approval.alert_history import prune
    with pytest.raises(ValueError):
        prune(older_than_seconds=-1.0)


def test_prune_zero_raises(alert_data_dir: Path):
    from core.approval.alert_history import prune
    with pytest.raises(ValueError):
        prune(older_than_seconds=0)


def test_prune_no_file_no_op(alert_data_dir: Path):
    """No history file -- prune is a no-op, no error."""
    from core.approval.alert_history import prune
    removed = prune(older_than_seconds=86400.0, now=1000.0)
    assert removed == 0


# ─── Per-store scope (PR adding store_id field) ──────────────


def test_record_alerts_explicit_store_id(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, recent_history,
    )
    n = record_alerts(
        [_FakeAlert("loyalty")], now=1000.0, store_id="store_a",
    )
    assert n == 1
    events = recent_history(now=2000.0)
    assert events[0].store_id == "store_a"


def test_record_alerts_picks_up_active_store(
    alert_data_dir: Path,
):
    from core.context.active_store import active_store
    from core.approval.alert_history import (
        record_alerts, recent_history,
    )
    with active_store("store_b"):
        record_alerts([_FakeAlert("loyalty")], now=1000.0)
    events = recent_history(now=2000.0)
    assert events[0].store_id == "store_b"


def test_record_alerts_explicit_overrides_active_store(
    alert_data_dir: Path,
):
    """Explicit store_id wins over the thread-local."""
    from core.context.active_store import active_store
    from core.approval.alert_history import (
        record_alerts, recent_history,
    )
    with active_store("active"):
        record_alerts(
            [_FakeAlert("loyalty")],
            now=1000.0, store_id="explicit",
        )
    events = recent_history(now=2000.0)
    assert events[0].store_id == "explicit"


def test_record_alerts_no_scope_writes_none(
    alert_data_dir: Path,
):
    from core.approval.alert_history import (
        record_alerts, recent_history,
    )
    # No active_store, no explicit param
    record_alerts([_FakeAlert("loyalty")], now=1000.0)
    events = recent_history(now=2000.0)
    assert events[0].store_id is None


def test_recent_history_store_filter(alert_data_dir: Path):
    from core.approval.alert_history import (
        record_alerts, recent_history,
    )
    record_alerts(
        [_FakeAlert("loyalty")], now=1000.0, store_id="a",
    )
    record_alerts(
        [_FakeAlert("loyalty")], now=1100.0, store_id="b",
    )
    record_alerts(
        [_FakeAlert("loyalty")], now=1200.0,  # None
    )
    # Filter to store a
    events_a = recent_history(now=2000.0, store_id="a")
    assert len(events_a) == 1
    assert events_a[0].store_id == "a"
    # No filter = all
    all_ev = recent_history(now=2000.0)
    assert len(all_ev) == 3


def test_consecutive_runs_per_engine_filtered_by_store(
    alert_data_dir: Path,
):
    """When store_id is supplied, only events tagged with that
    store contribute to the bucket count."""
    from core.approval.alert_history import (
        record_alerts, consecutive_runs_per_engine,
    )
    day = 86400.0
    # store_a: 3 days
    for i in range(3):
        record_alerts(
            [_FakeAlert("loyalty")],
            now=day * i + 1, store_id="store_a",
        )
    # store_b: only 1 day
    record_alerts(
        [_FakeAlert("loyalty")],
        now=day * 0 + 1, store_id="store_b",
    )

    a = consecutive_runs_per_engine(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 3,
        store_id="store_a",
    )
    assert a == {"loyalty": 3}

    b = consecutive_runs_per_engine(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 3,
        store_id="store_b",
    )
    assert b == {"loyalty": 1}

    # No filter: 3 distinct days (one bucket per day,
    # multiple events in the same bucket count once)
    fleet = consecutive_runs_per_engine(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 3,
    )
    assert fleet == {"loyalty": 3}


def test_consecutive_runs_per_engine_store_pair_table(
    alert_data_dir: Path,
):
    """The (engine, store) variant breaks streaks down per
    pair so the bridge can act per-store."""
    from core.approval.alert_history import (
        record_alerts, consecutive_runs_per_engine_store,
    )
    day = 86400.0
    # loyalty on store_a: 3 days, on store_b: 1 day
    for i in range(3):
        record_alerts(
            [_FakeAlert("loyalty")],
            now=day * i + 1, store_id="store_a",
        )
    record_alerts(
        [_FakeAlert("loyalty")],
        now=day * 0 + 1, store_id="store_b",
    )
    # affiliate fleet-wide: 2 days
    record_alerts(
        [_FakeAlert("affiliate")], now=day * 0 + 1,
    )
    record_alerts(
        [_FakeAlert("affiliate")], now=day * 1 + 1,
    )

    out = consecutive_runs_per_engine_store(
        window_seconds=day * 7,
        bucket_seconds=day,
        now=day * 3,
    )
    assert out == {
        ("loyalty", "store_a"): 3,
        ("loyalty", "store_b"): 1,
        ("affiliate", None): 2,
    }


def test_backward_compat_legacy_json_loads_with_none_store(
    alert_data_dir: Path,
):
    """Old alert_history.json without store_id field should
    load cleanly with store_id=None."""
    from core.approval.alert_history import recent_history
    legacy_payload = [
        {
            "engine": "loyalty",
            "recorded_at": 1000.0,
            "drop": 0.3,
            "recent_score": 0.4,
            "baseline_score": 0.7,
            # no store_id key
        },
    ]
    (alert_data_dir / "alert_history.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8",
    )
    events = recent_history(since_seconds=86400.0, now=2000.0)
    assert len(events) == 1
    assert events[0].engine == "loyalty"
    assert events[0].store_id is None
