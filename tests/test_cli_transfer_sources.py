"""Tests for ``shopai transfer sources`` -- pre-suggest helper
that ranks fleet stores by transferable surface area to a target.

Operators currently have to guess which source to point
``transfer suggest --from`` at. This surface answers: 'these are
the stores with the most successful actions that target hasn't
tried yet'.

Covers:

  - --to required
  - Target itself excluded from candidate list
  - transferable_count = source EXECUTED set minus target's
    "any-status" set (matches ``transfer suggest`` exclusion)
  - Source with no exec rows still surfaces (count=0)
  - Ranking: transferable_count desc, then total_executed desc
  - Pre-#239 queue (no store_id kwarg) → clean error
  - JSON envelope shape
  - Sample transferable list capped at 5 sorted items
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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
    defaults = dict(to_store="target", k=5, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _action(*, engine, action_type):
    a = MagicMock()
    a.engine = engine
    a.action_type = action_type
    return a


def _fake_sm(store_ids):
    sm = MagicMock()
    sm.list_stores.return_value = [
        {"store_id": sid} for sid in store_ids
    ]
    return sm


def _fake_queue(
    *,
    target_by_status=None,
    source_executed=None,
    list_raises=None,
):
    """Stub queue.list_by_status with per-store data.

    ``target_by_status`` is ``{status_value: [actions]}`` for the
    target store; ``source_executed`` is ``{store_id: [actions]}``
    for EXECUTED rows on each source store.
    """
    from core.approval.queue import ApprovalStatus

    target_by_status = target_by_status or {}
    source_executed = source_executed or {}
    q = MagicMock()

    def _list(status, *, engine=None, store_id=None, limit=2000):
        if list_raises is not None:
            raise list_raises
        if store_id == "target":
            return list(
                target_by_status.get(status.value, []),
            )[:limit]
        if status == ApprovalStatus.EXECUTED:
            return list(
                source_executed.get(store_id, []),
            )[:limit]
        return []

    q.list_by_status.side_effect = _list
    return q


# ─── Arg validation ──────────────────────────────────────────


class TestArgValidation:

    def test_missing_to_fails(self, cli):
        out, code = _capture(
            cli._cmd_transfer_sources, _ns(to_store=""),
        )
        assert code == 1
        assert "--to is required" in out


# ─── Target exclusion ────────────────────────────────────────


class TestTargetExclusion:

    def test_target_excluded_from_candidates(self, cli):
        """The target store should never appear in its own
        sources list."""
        sm = _fake_sm(["target", "a", "b"])
        q = _fake_queue(source_executed={
            "a": [_action(engine="loyalty", action_type="mint")],
            "b": [_action(engine="cart", action_type="recover")],
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        sids = {s["store_id"] for s in data["sources"]}
        assert "target" not in sids
        assert sids == {"a", "b"}


# ─── Transferable count semantics ────────────────────────────


class TestTransferableCount:

    def test_target_tried_excludes_from_transferable(self, cli):
        """An action target has already tried (in ANY status)
        should be excluded from transferable_count, matching the
        same exclusion logic as ``transfer suggest``."""
        sm = _fake_sm(["target", "src"])
        q = _fake_queue(
            target_by_status={
                # Target already has loyalty/mint in any status.
                "executed": [
                    _action(engine="loyalty", action_type="mint"),
                ],
            },
            source_executed={
                "src": [
                    _action(engine="loyalty", action_type="mint"),
                    _action(engine="cart", action_type="recover"),
                ],
            },
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        data = json.loads(out)
        src = next(
            s for s in data["sources"] if s["store_id"] == "src"
        )
        # loyalty/mint already on target, cart/recover not -- so 1.
        assert src["transferable_count"] == 1
        # Source has 2 unique actions executed.
        assert src["source_unique_actions"] == 2
        # Source had 2 total executed rows.
        assert src["source_executed_total"] == 2

    def test_pending_on_target_also_blocks_transferable(self, cli):
        """A PENDING (or any non-executed status) on target
        should still block the (engine, action_type) -- the
        operator has at least considered it."""
        sm = _fake_sm(["target", "src"])
        q = _fake_queue(
            target_by_status={
                "pending": [
                    _action(engine="loyalty", action_type="mint"),
                ],
            },
            source_executed={
                "src": [
                    _action(engine="loyalty", action_type="mint"),
                ],
            },
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        data = json.loads(out)
        src = next(
            s for s in data["sources"] if s["store_id"] == "src"
        )
        assert src["transferable_count"] == 0

    def test_source_with_no_execs_surfaces(self, cli):
        """A store with zero executed actions should still
        appear in the candidates list (count=0). Useful signal:
        'these stores have nothing to offer'."""
        sm = _fake_sm(["target", "empty_src"])
        q = _fake_queue(source_executed={})
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        data = json.loads(out)
        sids = {s["store_id"] for s in data["sources"]}
        assert "empty_src" in sids
        empty = next(
            s for s in data["sources"]
            if s["store_id"] == "empty_src"
        )
        assert empty["transferable_count"] == 0


# ─── Ranking ─────────────────────────────────────────────────


class TestRanking:

    def test_highest_transferable_count_first(self, cli):
        sm = _fake_sm(["target", "rich", "poor"])
        q = _fake_queue(source_executed={
            "rich": [
                _action(engine="e1", action_type="t1"),
                _action(engine="e2", action_type="t2"),
                _action(engine="e3", action_type="t3"),
            ],
            "poor": [
                _action(engine="ex", action_type="tx"),
            ],
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        data = json.loads(out)
        ranked = [s["store_id"] for s in data["sources"]]
        assert ranked == ["rich", "poor"]


# ─── Pre-#239 queue rejection ────────────────────────────────


class TestLegacyQueueRejection:

    def test_typeerror_on_store_id_surfaces_clear_error(self, cli):
        sm = _fake_sm(["target", "a"])
        q = _fake_queue(
            list_raises=TypeError(
                "unexpected keyword argument 'store_id'"
            ),
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "per-store" in data["error"]


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_fields(self, cli):
        sm = _fake_sm(["target", "a"])
        q = _fake_queue(source_executed={
            "a": [_action(engine="loyalty", action_type="mint")],
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(json=True, k=3),
            )
        data = json.loads(out)
        for key in (
            "to_store", "k", "target_already_tried_count",
            "candidate_count", "sources",
        ):
            assert key in data
        assert data["to_store"] == "target"
        assert data["k"] == 3
        assert data["candidate_count"] == 1
        src = data["sources"][0]
        for key in (
            "store_id", "source_executed_total",
            "source_unique_actions", "transferable_count",
            "sample_transferable",
        ):
            assert key in src

    def test_sample_transferable_capped_at_five(self, cli):
        sm = _fake_sm(["target", "src"])
        # 10 distinct transferable actions
        execs = [
            _action(engine=f"e{i}", action_type=f"t{i}")
            for i in range(10)
        ]
        q = _fake_queue(source_executed={"src": execs})
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(json=True),
            )
        data = json.loads(out)
        src = data["sources"][0]
        assert src["transferable_count"] == 10
        assert len(src["sample_transferable"]) == 5
        # Sorted (lexicographic on "engine/action_type")
        assert src["sample_transferable"] == sorted(
            src["sample_transferable"],
        )


# ─── Text mode renders hint ──────────────────────────────────


class TestTextMode:

    def test_text_includes_next_step_hint(self, cli):
        sm = _fake_sm(["target", "a"])
        q = _fake_queue(source_executed={
            "a": [_action(engine="loyalty", action_type="mint")],
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_sources, _ns(),
            )
        assert "shopai transfer suggest --from a --to target" in out

    def test_text_no_candidates(self, cli):
        sm = _fake_sm(["target"])
        q = _fake_queue()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_sources, _ns(),
            )
        assert code == 0
        assert "No candidate stores" in out
