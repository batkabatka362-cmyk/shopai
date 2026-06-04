"""Tests for engines.fleet_transfer_auto — W963-27."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.fleet_transfer_auto import FleetTransferAutoEngine
from engines.fleet_transfer_auto.applier import (
    AppliedTransfer,
    FleetTransferReport,
    apply_fleet_transfers,
)


def _fake_candidate(
    from_store="A", to_store="B", engine="loyalty",
    action_type="mint_code", capability="SHOPIFY_CREATE_DISCOUNT",
    score=4.5,
):
    c = MagicMock()
    c.from_store = from_store
    c.to_store = to_store
    c.engine = engine
    c.action_type = action_type
    c.capability = capability
    c.score = score
    return c


def _fake_template(capability="SHOPIFY_CREATE_DISCOUNT", params=None):
    t = MagicMock()
    t.action_type = "mint_code"
    t.capability = capability
    t.params = params or {"discount_pct": 10}
    return t


# ── apply_fleet_transfers ─────────────────────────────────


class TestApplyFleetTransfers:
    def test_no_candidates_empty_report(self):
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[],
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.candidates_scanned == 0
        assert r.enqueued_count == 0

    def test_dry_run_does_not_enqueue(self):
        cand = _fake_candidate()
        fake_queue = MagicMock()
        fake_queue.enqueue = MagicMock(
            return_value=MagicMock(id="action-1"),
        )
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_candidate_already_on_target",
            return_value=False,
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_resolve_template",
            return_value=_fake_template(),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=False)
        assert r.enqueued_count == 0
        assert r.skip_count == 1
        assert r.skip_reasons.get("dry_run") == 1
        assert not fake_queue.enqueue.called

    def test_already_on_target_skipped(self):
        cand = _fake_candidate()
        fake_queue = MagicMock()
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_candidate_already_on_target",
            return_value=True,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.enqueued_count == 0
        assert r.skip_reasons.get("already_on_target") == 1

    def test_missing_template_skipped(self):
        cand = _fake_candidate()
        fake_queue = MagicMock()
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_candidate_already_on_target",
            return_value=False,
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_resolve_template",
            return_value=None,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.enqueued_count == 0
        assert r.skip_reasons.get("no_template") == 1

    def test_same_store_skipped(self):
        cand = _fake_candidate(from_store="X", to_store="X")
        fake_queue = MagicMock()
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.enqueued_count == 0
        assert r.skip_reasons.get("same_store") == 1

    def test_missing_fields_skipped(self):
        cand = _fake_candidate(engine="")
        fake_queue = MagicMock()
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.skip_reasons.get("missing_fields") == 1

    def test_pair_cap_enforced(self):
        # 3 candidates all for same (A, B) pair, max_per_pair=2
        cands = [
            _fake_candidate(action_type="t1"),
            _fake_candidate(action_type="t2"),
            _fake_candidate(action_type="t3"),
        ]
        fake_queue = MagicMock()
        fake_queue.enqueue = MagicMock(
            return_value=MagicMock(id="X"),
        )
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=cands,
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_candidate_already_on_target",
            return_value=False,
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_resolve_template",
            return_value=_fake_template(),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(
                confirmed=True, max_per_pair=2,
            )
        assert r.enqueued_count == 2
        assert r.skip_reasons.get("pair_cap") == 1

    def test_enqueue_success_path(self):
        cand = _fake_candidate()
        fake_queue = MagicMock()
        fake_queue.enqueue = MagicMock(
            return_value=MagicMock(id="action-99"),
        )
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_candidate_already_on_target",
            return_value=False,
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_resolve_template",
            return_value=_fake_template(),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.enqueued_count == 1
        assert r.applied[0].enqueued is True
        assert r.applied[0].action_id == "action-99"
        # Verify enqueue called with right store_id
        kwargs = fake_queue.enqueue.call_args.kwargs
        assert kwargs.get("store_id") == "B"
        assert kwargs.get("engine") == "loyalty"

    def test_enqueue_exception_captured(self):
        cand = _fake_candidate()
        fake_queue = MagicMock()
        fake_queue.enqueue = MagicMock(
            side_effect=RuntimeError("db full"),
        )
        with patch(
            "engines.fleet_transfer_auto.applier."
            "_scan_candidates",
            return_value=[cand],
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_candidate_already_on_target",
            return_value=False,
        ), patch(
            "engines.fleet_transfer_auto.applier."
            "_resolve_template",
            return_value=_fake_template(),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = apply_fleet_transfers(confirmed=True)
        assert r.enqueued_count == 0
        assert r.skip_reasons.get("enqueue_failed") == 1
        # Applied row still present with reason
        assert any(
            "enqueue_failed" in (a.skip_reason or "")
            for a in r.applied
        )


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetTransferAutoEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = FleetTransferAutoEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetTransferAutoEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetTransferAutoEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetTransferAutoEngine().run({})
        assert r["meta"]["engine"] == "fleet_transfer_auto"


class TestEngineActions:
    def test_double_gate_yes_without_env_stays_dry_run(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPAI_FLEET_TRANSFER_AUTO", None)
            r = FleetTransferAutoEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["operator_confirmed"] is True
        assert r["data"]["env_gate_set"] is False
        assert r["data"]["confirmed"] is False

    def test_double_gate_env_without_yes_stays_dry_run(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_FLEET_TRANSFER_AUTO": "1"},
            clear=False,
        ):
            r = FleetTransferAutoEngine().run({})
        assert r["data"]["env_gate_set"] is True
        assert r["data"]["operator_confirmed"] is False
        assert r["data"]["confirmed"] is False

    def test_both_gates_set_confirms(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_FLEET_TRANSFER_AUTO": "1"},
            clear=False,
        ):
            r = FleetTransferAutoEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is True

    def test_invalid_min_positive_falls_back(self):
        r = FleetTransferAutoEngine().run({
            "data": {"min_positive": "abc"},
        })
        assert r["data"]["min_positive"] == 3

    def test_min_positive_floor(self):
        r = FleetTransferAutoEngine().run({
            "data": {"min_positive": 0},
        })
        # max(1, 0) = 1
        assert r["data"]["min_positive"] == 1

    def test_env_gate_whitespace_handled(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_FLEET_TRANSFER_AUTO": "1 "},
            clear=False,
        ):
            r = FleetTransferAutoEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["env_gate_set"] is True
