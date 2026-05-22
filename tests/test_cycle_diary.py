"""Tests for ``core.autonomous.cycle_diary``."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.autonomous import cycle_diary as cd


def _cycle_event(ts=1700000000.0, **kw):
    from core.autonomous.cycle_history import CycleEvent
    defaults = dict(
        recorded_at=ts,
        executed=True,
        advance={
            "executed_ok": 2,
            "refused_reliability": 0,
        },
        defend={},
        correlate={},
        flags={},
    )
    defaults.update(kw)
    return CycleEvent(**defaults)


def _demote_event(ts=1700000100.0, **kw):
    from core.capability_planner.auto_demote_history import (
        AutoDemoteEvent,
    )
    defaults = dict(
        kind="demote",
        capability="cap_a",
        reason="auto_demote_degraded: x",
        recorded_at=ts,
    )
    defaults.update(kw)
    return AutoDemoteEvent(**defaults)


def _promote_event(ts=1700000200.0, **kw):
    from core.capability_planner.\
auto_promote_history import AutoPromoteEvent
    defaults = dict(
        capability="winner",
        reason="auto_promote_reliable: x",
        recorded_at=ts,
    )
    defaults.update(kw)
    return AutoPromoteEvent(**defaults)


def _relax_event(ts=1700000300.0, **kw):
    from core.autonomous.auto_relax_history import (
        RelaxHistoryEvent,
    )
    defaults = dict(
        direction="relax",
        current_value=0.9,
        proposed_value=0.85,
        reason="3d streak",
        recorded_at=ts,
    )
    defaults.update(kw)
    return RelaxHistoryEvent(**defaults)


def _transfer_event(ts=1700000400.0, **kw):
    from core.autonomous.transfer_history import (
        TransferEvent,
    )
    defaults = dict(
        target_store_id="b",
        source_store_id="a",
        engine="loyalty",
        action_type="mint",
        capability="cap",
        recorded_at=ts,
        action_id="a1",
    )
    defaults.update(kw)
    return TransferEvent(**defaults)


def _alert_event(ts=1700000500.0, **kw):
    from core.autonomous.cycle_alert_history import (
        CycleAlertEvent,
    )
    defaults = dict(
        kind="stale_cycle",
        detail="48h ago",
        recorded_at=ts,
    )
    defaults.update(kw)
    return CycleAlertEvent(**defaults)


def _pause_event(ts=1700000450.0, **kw):
    defaults = dict(
        kind="pause",
        reason="maintenance",
        paused_until_at=ts + 3600.0,
        recorded_at=ts,
    )
    defaults.update(kw)
    return defaults


class TestCompileDiary:

    def test_empty_sources_returns_empty(self):
        with patch(
            "core.autonomous.cycle_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_promote_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.auto_relax_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_alert_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_pause."
            "pause_history",
            return_value=[],
        ):
            out = cd.compile_diary()
        assert out == []

    def test_all_sources_merge_in_order(self):
        with patch(
            "core.autonomous.cycle_history."
            "recent_history",
            return_value=[_cycle_event()],
        ), patch(
            "core.capability_planner.auto_demote_history."
            "recent_history",
            return_value=[_demote_event()],
        ), patch(
            "core.capability_planner.auto_promote_history."
            "recent_history",
            return_value=[_promote_event()],
        ), patch(
            "core.autonomous.auto_relax_history."
            "recent_history",
            return_value=[_relax_event()],
        ), patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=[_transfer_event()],
        ), patch(
            "core.autonomous.cycle_alert_history."
            "recent_history",
            return_value=[_alert_event()],
        ), patch(
            "core.autonomous.cycle_pause."
            "pause_history",
            return_value=[_pause_event()],
        ):
            out = cd.compile_diary()
        # All seven sources represented
        sources = {e.source for e in out}
        assert sources == {
            "cycle", "demote", "promote", "relax",
            "transfer", "pause", "alert",
        }
        # Newest first (alert at 500.0 is latest)
        assert out[0].source == "alert"
        assert out[-1].source == "cycle"  # 1700000000.0

    def test_demote_release_kinds_distinguished(self):
        demote = _demote_event(kind="demote")
        release = _demote_event(
            kind="release",
            ts=1700000600.0,
            reason="auto_demote_release: ...",
        )
        with patch(
            "core.autonomous.cycle_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote_history."
            "recent_history",
            return_value=[demote, release],
        ), patch(
            "core.capability_planner.auto_promote_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.auto_relax_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_alert_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_pause."
            "pause_history",
            return_value=[],
        ):
            out = cd.compile_diary()
        details = [e.detail for e in out]
        # Both DEMOTE and RELEASE verbs appear
        assert any("[DEMOTE]" in d for d in details)
        assert any("[RELEASE]" in d for d in details)

    def test_limit_caps_output(self):
        many = [
            _cycle_event(ts=float(i))
            for i in range(100)
        ]
        with patch(
            "core.autonomous.cycle_history."
            "recent_history",
            return_value=many,
        ), patch(
            "core.capability_planner.auto_demote_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_promote_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.auto_relax_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_alert_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_pause."
            "pause_history",
            return_value=[],
        ):
            out = cd.compile_diary(limit=10)
        assert len(out) == 10

    def test_one_source_failure_doesnt_break(self):
        """If auto_demote_history raises, the diary still
        returns events from other sources."""
        with patch(
            "core.autonomous.cycle_history."
            "recent_history",
            return_value=[_cycle_event()],
        ), patch(
            "core.capability_planner.auto_demote_history."
            "recent_history",
            side_effect=RuntimeError("disk"),
        ), patch(
            "core.capability_planner.auto_promote_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.auto_relax_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_alert_history."
            "recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_pause."
            "pause_history",
            return_value=[],
        ):
            out = cd.compile_diary()
        # Cycle event still surfaces
        sources = {e.source for e in out}
        assert "cycle" in sources
        assert "demote" not in sources
