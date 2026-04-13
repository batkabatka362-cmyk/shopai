"""Dashboard cycle + vault visibility — scheduler buffer & vault summary.

Exercises the Option C wiring:

* ``AutoScheduler._compact_summary`` — deliberately drops heavy payloads
  from cycle results so the dashboard's ``/api/cycle`` stays small.
* ``AutoScheduler._recent_summaries`` — deque(maxlen=20), history buffer.
* ``AutoScheduler.record_cycle_result`` — external hook for callers who
  bypass the scheduler loop.
* ``dashboard.app._collect_vault_summary`` — reads the configured
  Obsidian vault and produces the Vault tab's JSON payload.

All functions must fail soft: a missing vault, an unparseable note, or
no cycle ever running must never raise."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.system.auto_scheduler import (
    AutoScheduler,
    _compact_summary,
    _RECENT_SUMMARIES_MAX,
)
from dashboard.app import _collect_vault_summary


# ---------------------------------------------------------------------------
# _compact_summary — pure helper
# ---------------------------------------------------------------------------


def _full_cycle_result(**overrides) -> dict:
    """Produce a realistic ``run_cycle`` result for summary tests."""
    base = {
        "cycle_id": "cyc-abc123",
        "store_id": "deguar",
        "timestamp": 1700000000.0,
        "duration_s": 2.75,
        "status": "complete",
        "phase_error_count": 0,
        "phase_errors": {},
        "phases": {
            "data": {
                "products": 42,
                "orders": 7,
                "customers": 13,
                "raw_blob": "x" * 10000,  # heavy, must be dropped
            },
            "analysis": {"insights": 3},
            "decisions": {"proposed": 5, "full_list": list(range(200))},
            "brain": {"top_action": "increase_ads", "health_score": 0.87},
            "adapter_hooks": {
                "enabled": True,
                "analytics": {"cycle_event": {"ok": True}, "order_events": 2},
                "crm": {"synced": 4, "skipped": 1},
            },
        },
        "reflection": {"promoted": 2},
    }
    base.update(overrides)
    return base


class TestCompactSummary:
    def test_keeps_top_level_fields(self):
        out = _compact_summary(_full_cycle_result())
        assert out["cycle_id"] == "cyc-abc123"
        assert out["store_id"] == "deguar"
        assert out["duration_s"] == 2.75
        assert out["status"] == "complete"

    def test_pulls_phase_data(self):
        out = _compact_summary(_full_cycle_result())
        assert out["products"] == 42
        assert out["orders"] == 7
        assert out["customers"] == 13
        assert out["insights"] == 3
        assert out["actions_proposed"] == 5
        assert out["top_action"] == "increase_ads"
        assert out["health_score"] == 0.87

    def test_drops_heavy_payloads(self):
        """The ``raw_blob`` and ``full_list`` must not leak through."""
        out = _compact_summary(_full_cycle_result())
        assert "raw_blob" not in str(out)
        # ``full_list`` is a 200-int list; if it leaks, the serialized
        # summary will balloon past ~2KB.
        import json
        assert len(json.dumps(out, default=str)) < 2000

    def test_preserves_adapter_hooks(self):
        out = _compact_summary(_full_cycle_result())
        hooks = out["adapter_hooks"]
        assert hooks["analytics"]["cycle_event"]["ok"] is True
        assert hooks["crm"]["synced"] == 4

    def test_preserves_reflection(self):
        out = _compact_summary(_full_cycle_result())
        assert out["reflection"] == {"promoted": 2}

    def test_empty_result_yields_defaults(self):
        """An empty dict must produce zeroed defaults, never raise."""
        out = _compact_summary({})
        assert out["cycle_id"] == ""
        assert out["store_id"] == ""
        assert out["duration_s"] == 0.0
        assert out["products"] == 0
        assert out["phase_error_count"] == 0
        assert out["adapter_hooks"] == {}

    def test_missing_phases_dict_is_tolerant(self):
        out = _compact_summary({"cycle_id": "c1"})
        assert out["cycle_id"] == "c1"
        assert out["products"] == 0
        assert out["top_action"] == ""


# ---------------------------------------------------------------------------
# AutoScheduler — ring buffer + record_cycle_result
# ---------------------------------------------------------------------------


class TestSchedulerBuffer:
    def test_new_scheduler_has_empty_buffer(self):
        s = AutoScheduler()
        assert s.get_last_summary() is None
        assert s.get_recent_summaries() == []

    def test_record_cycle_result_appends(self):
        s = AutoScheduler()
        s.record_cycle_result(_full_cycle_result(cycle_id="c1"))
        s.record_cycle_result(_full_cycle_result(cycle_id="c2"))
        recent = s.get_recent_summaries()
        assert len(recent) == 2
        assert recent[0]["cycle_id"] == "c1"
        assert recent[1]["cycle_id"] == "c2"

    def test_last_summary_reflects_most_recent(self):
        s = AutoScheduler()
        s.record_cycle_result(_full_cycle_result(cycle_id="c1"))
        s.record_cycle_result(_full_cycle_result(cycle_id="c2"))
        last = s.get_last_summary()
        assert last is not None
        assert last["cycle_id"] == "c2"

    def test_buffer_respects_maxlen(self):
        s = AutoScheduler()
        overflow = _RECENT_SUMMARIES_MAX + 5
        for i in range(overflow):
            s.record_cycle_result(_full_cycle_result(cycle_id=f"c{i}"))
        recent = s.get_recent_summaries(limit=100)
        assert len(recent) == _RECENT_SUMMARIES_MAX
        # Oldest entries dropped — the first kept should be c5.
        assert recent[0]["cycle_id"] == f"c{overflow - _RECENT_SUMMARIES_MAX}"
        assert recent[-1]["cycle_id"] == f"c{overflow - 1}"

    def test_get_recent_limit_zero_returns_empty(self):
        s = AutoScheduler()
        s.record_cycle_result(_full_cycle_result())
        assert s.get_recent_summaries(limit=0) == []

    def test_get_recent_limit_smaller_than_buffer(self):
        s = AutoScheduler()
        for i in range(5):
            s.record_cycle_result(_full_cycle_result(cycle_id=f"c{i}"))
        recent = s.get_recent_summaries(limit=2)
        assert len(recent) == 2
        # Limit trims oldest; we get the tail.
        assert recent[-1]["cycle_id"] == "c4"

    def test_record_rejects_non_dict(self):
        """A bad caller must not corrupt the ring."""
        s = AutoScheduler()
        s.record_cycle_result("not a dict")  # type: ignore[arg-type]
        s.record_cycle_result(None)  # type: ignore[arg-type]
        s.record_cycle_result(42)  # type: ignore[arg-type]
        assert s.get_last_summary() is None
        assert s.get_recent_summaries() == []


# ---------------------------------------------------------------------------
# _collect_vault_summary — vault reader
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_env(monkeypatch):
    """Strip OBSIDIAN_VAULT_PATH from env + config cache."""
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    from core.adapters import reset_config
    reset_config()
    yield
    reset_config()


@pytest.fixture
def seeded_vault(tmp_path, monkeypatch):
    """Build a small vault directory tree and point config at it."""
    vault = tmp_path / "vault"
    (vault / "Wins").mkdir(parents=True)
    (vault / "Errors").mkdir()
    (vault / "Decisions").mkdir()
    (vault / "Concepts").mkdir()
    (vault / "Knowledge").mkdir()
    (vault / "ShopAI" / "Learned").mkdir(parents=True)

    (vault / "Wins" / "First Win.md").write_text(
        "---\ntitle: First Win\ntags: [win]\n---\n\nYay.\n"
    )
    (vault / "Wins" / "Second Win.md").write_text(
        "---\ntitle: Second Win\ntags: [win, milestone]\n---\n\nAlso good.\n"
    )
    (vault / "Errors" / "Known Error.md").write_text(
        "---\ntitle: Known Error\ntags: [error]\n---\n\nOops.\n"
    )
    (vault / "Decisions" / "ADR-001.md").write_text(
        "---\ntitle: ADR-001\ntags: [decision]\n---\n\nDecided.\n"
    )
    (vault / "Concepts" / "Brain.md").write_text(
        "---\ntitle: Brain\n---\n\nThe brain.\n"
    )
    (vault / "ShopAI" / "Learned" / "pattern-1.md").write_text(
        "---\ntitle: pattern-1\ncycle_id: cyc-xyz\naction: increase_ads\n---\n\nExport.\n"
    )

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    from core.adapters import reset_config
    reset_config()
    yield vault
    reset_config()


class TestVaultSummaryHelper:
    def test_unconfigured_returns_empty_shape(self, empty_env):
        out = _collect_vault_summary()
        assert out["configured"] is False
        assert out["totals"] == {}
        assert out["recent_wins"] == []
        assert out["recent_errors"] == []
        assert out["recent_decisions"] == []
        assert out["recent_learned"] == []

    def test_missing_directory_returns_empty_shape(self, tmp_path, monkeypatch):
        nonexistent = tmp_path / "does_not_exist"
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(nonexistent))
        from core.adapters import reset_config
        reset_config()
        try:
            out = _collect_vault_summary()
            assert out["configured"] is False
            assert out["path"] == str(nonexistent)
        finally:
            reset_config()

    def test_seeded_vault_counts_folders(self, seeded_vault):
        out = _collect_vault_summary()
        assert out["configured"] is True
        assert Path(out["path"]) == seeded_vault
        totals = out["totals"]
        assert totals["Wins"] == 2
        assert totals["Errors"] == 1
        assert totals["Decisions"] == 1
        assert totals["Concepts"] == 1
        assert totals["ShopAI/Learned"] == 1
        assert totals["total"] == 6  # all .md files combined

    def test_seeded_vault_recent_wins_parsed(self, seeded_vault):
        out = _collect_vault_summary()
        titles = [w["title"] for w in out["recent_wins"]]
        assert "First Win" in titles
        assert "Second Win" in titles
        for w in out["recent_wins"]:
            assert w["folder"] == "Wins"
            assert "mtime" in w

    def test_seeded_vault_recent_learned_includes_cycle_meta(self, seeded_vault):
        out = _collect_vault_summary()
        assert len(out["recent_learned"]) == 1
        entry = out["recent_learned"][0]
        assert entry["cycle_id"] == "cyc-xyz"
        assert entry["action"] == "increase_ads"

    def test_shape_always_contains_all_keys(self, empty_env):
        """Frontend relies on these keys existing even when unconfigured."""
        out = _collect_vault_summary()
        for key in ("configured", "path", "totals", "recent_wins",
                    "recent_errors", "recent_decisions", "recent_learned"):
            assert key in out, f"missing key: {key}"
