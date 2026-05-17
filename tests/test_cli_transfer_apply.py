"""Tests for ``shopai transfer apply`` -- closes the suggest→action
loop in the empire-AGI cross-store transfer flow.

``transfer suggest`` shows recommendations; ``transfer apply`` turns
one of them into a real PENDING action on the target store. The
command reads the most recent EXECUTED action of the matching
(engine, action_type) on the source store as a params template,
then enqueues a new PENDING on the target.

Covers:

  - --from == --to rejected
  - --params-json malformed / non-dict rejected
  - No successful source action → clean error
  - Target already has the (engine, action_type) → duplicate-protect
  - Happy path: enqueue succeeds, narrative + params surface
  - Operator --narrative prepends to the auto-generated transfer note
  - --params-json overrides merge into source template
  - JSON envelope shape
  - Pre-#239 queue (no store_id kwarg) → clean error
  - Enqueue failure surfaces error, not crash
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
    defaults = dict(
        from_store="a", to_store="b",
        engine="loyalty",
        action_type="mint_loyalty_code",
        params_json="",
        narrative="",
        json=False,
        dry_run=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _action(
    *, id_, engine, action_type,
    capability="SHOPIFY_CREATE_DISCOUNT",
    store_id=None, params=None,
):
    a = MagicMock()
    a.id = id_
    a.engine = engine
    a.action_type = action_type
    a.capability = capability
    a.store_id = store_id
    a.params = params or {}
    return a


def _fake_queue(
    *,
    source_actions=None,
    target_actions_by_status=None,
    enqueue_result=None,
    enqueue_raises=None,
):
    """Build a queue that returns ``source_actions`` for EXECUTED on
    store 'a' and ``target_actions_by_status`` per-status on store 'b'.

    ``enqueue`` returns a MagicMock with ``id="appr_new"`` unless
    overridden via ``enqueue_result`` or ``enqueue_raises``.
    """
    from core.approval.queue import ApprovalStatus

    q = MagicMock()
    source_actions = source_actions or []
    target_actions_by_status = target_actions_by_status or {}

    def _list(status, *, engine=None, store_id=None, limit=2000):
        if store_id == "a":
            base = (
                list(source_actions)
                if status == ApprovalStatus.EXECUTED
                else []
            )
        elif store_id == "b":
            base = list(
                target_actions_by_status.get(status.value, []),
            )
        else:
            return []
        if engine:
            base = [a for a in base if a.engine == engine]
        return base[:limit]

    q.list_by_status.side_effect = _list

    if enqueue_raises is not None:
        q.enqueue.side_effect = enqueue_raises
    else:
        action = enqueue_result or MagicMock(id="appr_new")
        q.enqueue.return_value = action

    return q


# ─── Argument validation ─────────────────────────────────────


class TestArgValidation:

    def test_from_eq_to_fails(self, cli):
        out, code = _capture(
            cli._cmd_transfer_apply,
            _ns(from_store="x", to_store="x"),
        )
        assert code == 1
        assert "must be different" in out

    def test_params_json_invalid_rejected(self, cli):
        out, code = _capture(
            cli._cmd_transfer_apply,
            _ns(params_json="not-json{{"),
        )
        assert code == 1
        assert "not valid JSON" in out

    def test_params_json_non_dict_rejected(self, cli):
        out, code = _capture(
            cli._cmd_transfer_apply,
            _ns(params_json='["a", "b"]'),
        )
        assert code == 1
        assert "must be a JSON object" in out


# ─── Source template lookup ──────────────────────────────────


class TestSourceLookup:

    def test_no_match_on_source_fails_cleanly(self, cli):
        # Source has EXECUTED actions but none match the action_type.
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="some_other_type",
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(),
            )
        assert code == 1
        assert "no successful" in out
        assert "mint_loyalty_code" in out

    def test_empty_source_fails_cleanly(self, cli):
        q = _fake_queue(source_actions=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(),
            )
        assert code == 1
        assert "no successful" in out


# ─── Target duplicate-protection ─────────────────────────────


class TestTargetDuplicateProtection:

    def test_target_already_executed_blocks_apply(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            target_actions_by_status={
                "executed": [
                    _action(
                        id_="tgt1", engine="loyalty",
                        action_type="mint_loyalty_code",
                    ),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(),
            )
        assert code == 1
        assert "already exists on target" in out

    def test_target_pending_blocks_apply(self, cli):
        """Even a PENDING on target means operator has already seen
        / considered this; don't double-enqueue."""
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            target_actions_by_status={
                "pending": [
                    _action(
                        id_="tgt_pend", engine="loyalty",
                        action_type="mint_loyalty_code",
                    ),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(),
            )
        assert code == 1
        assert "already exists on target" in out
        # Status leaked to operator so they can diagnose.
        assert "pending" in out


# ─── Happy path / enqueue ────────────────────────────────────


class TestHappyPath:

    def test_basic_apply_enqueues_pending(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                    capability="SHOPIFY_CREATE_DISCOUNT",
                    params={"customer_id": "gid://X/1",
                            "discount_pct": 10},
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "ok"
        assert data["action_id"] == "appr_new"
        assert data["engine"] == "loyalty"
        assert data["action_type"] == "mint_loyalty_code"
        assert data["capability"] == "SHOPIFY_CREATE_DISCOUNT"
        assert data["from_store"] == "a"
        assert data["to_store"] == "b"
        # Source params copied through unchanged.
        assert data["params"]["customer_id"] == "gid://X/1"
        assert data["params"]["discount_pct"] == 10
        # Enqueue called with store_id=to_store + PENDING semantics.
        kwargs = q.enqueue.call_args.kwargs
        assert kwargs["engine"] == "loyalty"
        assert kwargs["action_type"] == "mint_loyalty_code"
        assert kwargs["store_id"] == "b"

    def test_narrative_auto_generated(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
                _action(
                    id_="src2", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
                _action(
                    id_="src3", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Count of prior runs surfaced in narrative.
        assert "3 prior successful run(s)" in data["narrative"]
        assert "from a to b" in data["narrative"]

    def test_operator_narrative_prepended(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(json=True, narrative="black friday parity"),
            )
        assert code == 0
        data = json.loads(out)
        # Operator note leads, auto-generated note follows.
        assert data["narrative"].startswith("black friday parity")
        assert "Transfer suggestion" in data["narrative"]

    def test_params_json_override_merges(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                    params={"customer_id": "gid://X/1",
                            "discount_pct": 10},
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(
                    json=True,
                    params_json=json.dumps(
                        {"customer_id": "gid://X/NEW"},
                    ),
                ),
            )
        assert code == 0
        data = json.loads(out)
        # Override wins for the touched key.
        assert data["params"]["customer_id"] == "gid://X/NEW"
        # Untouched keys preserved from source template.
        assert data["params"]["discount_pct"] == 10

    def test_picks_most_recent_when_multiple_source_matches(self, cli):
        """``list_by_status(EXECUTED, ...)`` returns rows ordered
        descending by ``decided_at`` -- the apply handler takes the
        first match as the template."""
        most_recent = _action(
            id_="src_recent", engine="loyalty",
            action_type="mint_loyalty_code",
            params={"customer_id": "newest"},
        )
        older = _action(
            id_="src_old", engine="loyalty",
            action_type="mint_loyalty_code",
            params={"customer_id": "oldest"},
        )
        q = _fake_queue(source_actions=[most_recent, older])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["params"]["customer_id"] == "newest"


# ─── Pre-#239 queue rejection ────────────────────────────────


class TestLegacyQueueRejection:

    def test_typeerror_on_store_id_surfaces_clear_error(self, cli):
        """A queue that predates PR #239 won't accept ``store_id`` on
        ``list_by_status``. Surface a useful pointer instead of
        the raw TypeError."""
        q = MagicMock()
        q.list_by_status.side_effect = TypeError(
            "unexpected keyword argument 'store_id'"
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "per-store" in data["error"]


# ─── Enqueue failure resilience ──────────────────────────────


class TestEnqueueFailure:

    def test_enqueue_raises_clean_error(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            enqueue_raises=RuntimeError("queue full"),
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "enqueue failed" in data["error"]
        assert "queue full" in data["error"]


# ─── --dry-run preview ───────────────────────────────────────


class TestDryRun:

    def test_dry_run_does_not_enqueue(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                    params={"customer_id": "gid://X/1"},
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(json=True, dry_run=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "dry_run"
        assert data["would_enqueue"] is True
        # No actual enqueue happens.
        q.enqueue.assert_not_called()

    def test_dry_run_envelope_carries_preview_fields(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src_template", engine="loyalty",
                    action_type="mint_loyalty_code",
                    capability="SHOPIFY_CREATE_DISCOUNT",
                    params={"customer_id": "gid://X/1",
                            "discount_pct": 10},
                ),
                _action(
                    id_="src_old", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(json=True, dry_run=True),
            )
        assert code == 0
        data = json.loads(out)
        # All fields a real apply envelope has, plus dry-run signals.
        assert data["engine"] == "loyalty"
        assert data["action_type"] == "mint_loyalty_code"
        assert data["capability"] == "SHOPIFY_CREATE_DISCOUNT"
        assert data["from_store"] == "a"
        assert data["to_store"] == "b"
        assert data["params"]["discount_pct"] == 10
        # Dry-run exposes the source template id (the real apply
        # envelope doesn't -- this is for operator audit).
        assert data["source_action_id"] == "src_template"
        assert data["source_run_count"] == 2
        # Narrative built the same way as a real apply.
        assert "Transfer suggestion" in data["narrative"]

    def test_dry_run_still_validates_source(self, cli):
        """Dry-run respects the same source-lookup gate as real
        apply -- no template means the operator's preview is
        meaningless, surface the same error."""
        q = _fake_queue(source_actions=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(dry_run=True),
            )
        assert code == 1
        assert "no successful" in out

    def test_dry_run_still_validates_target_dup(self, cli):
        """Dry-run respects the target duplicate-protection gate.
        If the target already has this in any status, the
        preview is misleading -- surface the same error as real
        apply."""
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            target_actions_by_status={
                "executed": [
                    _action(
                        id_="tgt1", engine="loyalty",
                        action_type="mint_loyalty_code",
                    ),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(dry_run=True),
            )
        assert code == 1
        assert "already exists on target" in out
        # Still no enqueue attempt (correctness check).
        q.enqueue.assert_not_called()

    def test_dry_run_text_mode_marks_preview(self, cli):
        """Text mode marks the output as DRY RUN clearly so
        operators don't misread it as a successful enqueue."""
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(dry_run=True),
            )
        assert code == 0
        assert "DRY RUN" in out
        assert "Re-run without --dry-run" in out

    def test_dry_run_respects_params_override(self, cli):
        q = _fake_queue(
            source_actions=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                    params={"customer_id": "gid://X/1",
                            "discount_pct": 10},
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_apply,
                _ns(
                    json=True, dry_run=True,
                    params_json=json.dumps(
                        {"discount_pct": 20},
                    ),
                ),
            )
        assert code == 0
        data = json.loads(out)
        # Operator sees the OVERRIDDEN value, not the template's.
        assert data["params"]["discount_pct"] == 20
        # Untouched key still surfaces.
        assert data["params"]["customer_id"] == "gid://X/1"
