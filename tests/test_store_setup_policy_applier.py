"""Tests for ``engines.store_setup.policy_applier``.

The applier loops generated policies through the
``SHOPIFY_UPDATE_SHOP_POLICY`` adapter, records each
attempt via Pattern Z, and returns per-policy results.

Coverage:
  1. Empty / non-dict input returns zero applied.
  2. All policies succeed -> applied_count == N.
  3. Router unavailable -> all policies fail with the
     ``router_unavailable`` reason + each recorded.
  4. Per-policy failure isolation: one rejection doesn't
     skip the others.
  5. Adapter raise -> error captured in results + recording.
  6. store_id propagates to params on every recorded event.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.policy_applier import apply_policies


def _ok_result():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail_result(error: str):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestEmpty:

    def test_empty_dict(self):
        out = apply_policies({})
        assert out == {"applied_count": 0, "results": []}

    def test_non_dict(self):
        out = apply_policies(None)  # type: ignore[arg-type]
        assert out == {"applied_count": 0, "results": []}


class TestAllSuccess:

    def test_all_three_applied(self):
        router = MagicMock()
        router.execute.return_value = _ok_result()
        with patch(
            "engines.store_setup.policy_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.policy_applier."
            "record_writeback",
        ) as record_mock:
            out = apply_policies({
                "REFUND_POLICY": "<p>...</p>",
                "PRIVACY_POLICY": "<p>...</p>",
                "TERMS_OF_SERVICE": "<p>...</p>",
            })
        assert out["applied_count"] == 3
        assert len(out["results"]) == 3
        assert all(r["ok"] for r in out["results"])
        # All three recordings were success=True
        assert record_mock.call_count == 3
        for call in record_mock.call_args_list:
            assert call.kwargs["success"] is True


class TestRouterUnavailable:

    def test_all_policies_marked_failed(self):
        with patch(
            "engines.store_setup.policy_applier._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.policy_applier."
            "record_writeback",
        ) as record_mock:
            out = apply_policies({
                "REFUND_POLICY": "<p>...</p>",
                "PRIVACY_POLICY": "<p>...</p>",
            })
        assert out["applied_count"] == 0
        assert all(
            r["ok"] is False for r in out["results"]
        )
        assert all(
            r["error"] == "router_unavailable"
            for r in out["results"]
        )
        # Each policy still recorded as a failure
        assert record_mock.call_count == 2


class TestPartialFailure:

    def test_one_rejection_doesnt_block_others(self):
        # Adapter rejects PRIVACY but accepts the others
        def _by_policy(cap, params):
            if params["policy_type"] == "PRIVACY_POLICY":
                return _fail_result(
                    "body: missing GDPR clause",
                )
            return _ok_result()

        router = MagicMock()
        router.execute.side_effect = _by_policy
        with patch(
            "engines.store_setup.policy_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.policy_applier."
            "record_writeback",
        ) as record_mock:
            out = apply_policies({
                "REFUND_POLICY": "<p>r</p>",
                "PRIVACY_POLICY": "<p>p</p>",
                "TERMS_OF_SERVICE": "<p>t</p>",
            })
        # 2 succeeded, 1 failed
        assert out["applied_count"] == 2
        results_by_type = {
            r["policy_type"]: r for r in out["results"]
        }
        assert results_by_type["REFUND_POLICY"]["ok"] is True
        assert results_by_type["PRIVACY_POLICY"]["ok"] is False
        assert "GDPR" in results_by_type[
            "PRIVACY_POLICY"
        ]["error"]
        assert results_by_type[
            "TERMS_OF_SERVICE"
        ]["ok"] is True
        # All three recorded; success values mirror outcome
        success_flags = [
            c.kwargs["success"]
            for c in record_mock.call_args_list
        ]
        assert success_flags.count(True) == 2
        assert success_flags.count(False) == 1


class TestAdapterRaise:

    def test_exception_captured_in_results(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup.policy_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.policy_applier."
            "record_writeback",
        ) as record_mock:
            out = apply_policies({
                "REFUND_POLICY": "<p>r</p>",
            })
        assert out["applied_count"] == 0
        r = out["results"][0]
        assert r["ok"] is False
        assert "adapter_raise" in r["error"]
        assert "network" in r["error"]
        # Failure recorded
        assert record_mock.call_args.kwargs["success"] is False


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = MagicMock()
        router.execute.return_value = _ok_result()
        with patch(
            "engines.store_setup.policy_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.policy_applier."
            "record_writeback",
        ) as record_mock:
            apply_policies(
                {"REFUND_POLICY": "<p>r</p>"},
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
        assert params["policy_type"] == "REFUND_POLICY"
