"""Dead-letter ledger tests — Option Y.

Covers record → recent flow, file persistence + tail rehydrate,
filter semantics, size/prune bookkeeping, snapshot rollup,
singleton behaviour, and failure-path robustness.
"""
from __future__ import annotations

import json
import threading

import pytest

from core.adapters.deadletter import (
    DeadLetterEntry,
    DeadLetterLedger,
    get_dead_letter_ledger,
    iter_file_entries,
    recent_entries,
    reset_dead_letter_ledger,
)


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_dead_letter_ledger()
    yield
    reset_dead_letter_ledger()


def _rec(ledger, adapter="x", cap="chat_complete", err="timeout"):
    return ledger.record(
        adapter=adapter,
        capability=cap,
        params_hash="abc123",
        error_type="AdapterError",
        error_message=err,
        attempts=3,
    )


class TestRecord:
    def test_record_returns_entry_with_id_and_timestamp(self):
        clk = _Clock(1.0)
        lg = DeadLetterLedger(path=None, clock=clk)
        e = _rec(lg)
        assert e.id.startswith("dl-")
        assert e.timestamp == 1.0
        assert e.attempts == 3
        assert e.error_message == "timeout"

    def test_record_truncates_huge_error_message(self):
        lg = DeadLetterLedger(path=None)
        e = lg.record(
            adapter="x", capability="c", params_hash="h",
            error_type="Big", error_message="a" * 5000, attempts=1,
        )
        assert len(e.error_message) <= 500

    def test_memory_capped_at_max(self):
        lg = DeadLetterLedger(path=None, max_memory=3)
        for i in range(10):
            lg.record(
                adapter=f"a{i}", capability="c", params_hash="h",
                error_type="E", error_message=str(i), attempts=1,
            )
        assert lg.size() == 3
        rec = lg.recent()
        assert [e.error_message for e in rec] == ["9", "8", "7"]

    def test_recent_returns_newest_first(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg, err="first")
        _rec(lg, err="second")
        _rec(lg, err="third")
        out = lg.recent()
        assert [e.error_message for e in out] == ["third", "second", "first"]

    def test_recent_respects_limit(self):
        lg = DeadLetterLedger(path=None)
        for i in range(5):
            _rec(lg, err=str(i))
        assert len(lg.recent(limit=2)) == 2

    def test_negative_limit_rejected(self):
        lg = DeadLetterLedger(path=None)
        with pytest.raises(ValueError):
            lg.recent(limit=-1)


class TestFilter:
    def test_filter_by_adapter(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg, adapter="a")
        _rec(lg, adapter="b")
        _rec(lg, adapter="a")
        out = lg.filter(adapter="a")
        assert len(out) == 2
        assert all(e.adapter == "a" for e in out)

    def test_filter_by_capability(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg, cap="chat_complete")
        _rec(lg, cap="web_search")
        assert len(lg.filter(capability="chat_complete")) == 1

    def test_filter_by_since_ts(self):
        clk = _Clock(100.0)
        lg = DeadLetterLedger(path=None, clock=clk)
        _rec(lg, err="old")
        clk.advance(10)
        _rec(lg, err="mid")
        clk.advance(10)
        _rec(lg, err="new")
        out = lg.filter(since_ts=115.0)
        assert [e.error_message for e in out] == ["new"]

    def test_filter_combines_all_criteria(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg, adapter="a", cap="chat_complete")
        _rec(lg, adapter="b", cap="chat_complete")
        _rec(lg, adapter="a", cap="web_search")
        assert len(lg.filter(adapter="a", capability="chat_complete")) == 1


class TestPersistence:
    def test_append_creates_file(self, tmp_path):
        path = tmp_path / "deadletter.jsonl"
        lg = DeadLetterLedger(path=path)
        _rec(lg, err="disk")
        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["error_message"] == "disk"

    def test_append_creates_parent_dir(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "dl.jsonl"
        lg = DeadLetterLedger(path=path)
        _rec(lg)
        assert path.exists()

    def test_tail_rehydrates_memory(self, tmp_path):
        path = tmp_path / "dl.jsonl"
        lg = DeadLetterLedger(path=path, max_memory=5)
        for i in range(10):
            lg.record(
                adapter="a", capability="c", params_hash="h",
                error_type="E", error_message=str(i), attempts=1,
            )
        # New instance over the same file only keeps the tail.
        lg2 = DeadLetterLedger(path=path, max_memory=5)
        assert lg2.size() == 5
        rec = lg2.recent()
        assert [e.error_message for e in rec] == ["9", "8", "7", "6", "5"]

    def test_malformed_lines_are_skipped(self, tmp_path):
        path = tmp_path / "dl.jsonl"
        path.write_text(
            "not json\n"
            + json.dumps({
                "id": "dl-1", "adapter": "a", "capability": "c",
                "params_hash": "h", "params_snapshot": {}, "error_type": "E",
                "error_message": "legit", "attempts": 1, "timestamp": 1.0,
            }) + "\n"
            + "{bad json\n"
        )
        lg = DeadLetterLedger(path=path)
        # Only the one valid line should end up in memory.
        assert lg.size() == 1
        assert lg.recent()[0].error_message == "legit"

    def test_missing_file_is_not_an_error(self, tmp_path):
        path = tmp_path / "never_created.jsonl"
        lg = DeadLetterLedger(path=path)
        assert lg.size() == 0
        # Path still usable — first record creates the file.
        _rec(lg)
        assert path.exists()

    def test_iter_file_entries_yields_all(self, tmp_path):
        path = tmp_path / "dl.jsonl"
        lg = DeadLetterLedger(path=path, max_memory=2)
        for i in range(5):
            lg.record(
                adapter="a", capability="c", params_hash="h",
                error_type="E", error_message=str(i), attempts=1,
            )
        out = list(iter_file_entries(path))
        assert len(out) == 5

    def test_iter_file_entries_missing_path_is_empty(self, tmp_path):
        assert list(iter_file_entries(tmp_path / "missing")) == []


class TestSnapshot:
    def test_snapshot_counts(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg, adapter="a")
        _rec(lg, adapter="a")
        _rec(lg, adapter="b")
        snap = lg.snapshot()
        assert snap["size"] == 3
        assert snap["total_records"] == 3
        assert snap["per_adapter"] == {"a": 2, "b": 1}
        assert snap["per_capability"] == {"chat_complete": 3}

    def test_snapshot_empty_ledger(self):
        snap = DeadLetterLedger(path=None).snapshot()
        assert snap["size"] == 0
        assert snap["per_adapter"] == {}
        assert snap["newest_ts"] == 0.0

    def test_snapshot_includes_path(self, tmp_path):
        path = tmp_path / "dl.jsonl"
        lg = DeadLetterLedger(path=path)
        assert str(path) in (lg.snapshot()["path"] or "")


class TestPrune:
    def test_prune_all_clears(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg)
        _rec(lg)
        assert lg.prune() == 2
        assert lg.size() == 0

    def test_clear_returns_count(self):
        lg = DeadLetterLedger(path=None)
        _rec(lg)
        _rec(lg)
        assert lg.clear() == 2


class TestWriteFailure:
    def test_record_never_raises_on_disk_failure(self, tmp_path):
        path = tmp_path / "dl.jsonl"
        # Create as a directory so the file-open fails.
        path.mkdir()
        lg = DeadLetterLedger(path=path)
        # Must not raise even though append will fail.
        e = _rec(lg, err="still works")
        assert e.error_message == "still works"
        assert lg.size() == 1
        snap = lg.snapshot()
        assert snap["write_failures"] >= 1


class TestConstructorValidation:
    def test_zero_max_memory_rejected(self):
        with pytest.raises(ValueError):
            DeadLetterLedger(path=None, max_memory=0)


class TestSingleton:
    def test_get_returns_same_instance(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "SHOPAI_DEADLETTER_PATH", str(tmp_path / "dl.jsonl"),
        )
        a = get_dead_letter_ledger()
        b = get_dead_letter_ledger()
        assert a is b

    def test_reset_rebuilds(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "SHOPAI_DEADLETTER_PATH", str(tmp_path / "dl.jsonl"),
        )
        a = get_dead_letter_ledger()
        reset_dead_letter_ledger()
        b = get_dead_letter_ledger()
        assert a is not b

    def test_recent_entries_shortcut(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "SHOPAI_DEADLETTER_PATH", str(tmp_path / "dl.jsonl"),
        )
        lg = get_dead_letter_ledger()
        lg.record(
            adapter="a", capability="c", params_hash="h",
            error_type="E", error_message="m", attempts=1,
        )
        assert recent_entries()[0].error_message == "m"


class TestThreadSafety:
    def test_concurrent_records_do_not_corrupt_memory(self, tmp_path):
        path = tmp_path / "dl.jsonl"
        lg = DeadLetterLedger(path=path, max_memory=200)

        def worker(i: int):
            for j in range(20):
                lg.record(
                    adapter=f"a{i}", capability="c", params_hash="h",
                    error_type="E", error_message=f"{i}-{j}", attempts=1,
                )

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 20 threads × 20 records = 400, memory cap = 200.
        assert lg.size() == 200
        # All disk lines should parse as JSON.
        lines = path.read_text().splitlines()
        assert len(lines) == 400
        for raw in lines:
            json.loads(raw)
