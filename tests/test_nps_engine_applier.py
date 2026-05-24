"""Tests for engines.nps_engine.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.nps_engine.tag_applier import apply_nps_tags


def _resp(cid="c1", score=9, **extra):
    return {
        "customer_id": cid, "score": score,
        "comment": extra.pop("comment", ""),
        "date": extra.pop("date", ""),
        **extra,
    }


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "c1", "tags": []}, error=None,
    )
    return router


class TestTier:

    def test_promoter_9(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([_resp(score=9)])
        assert results[0]["tier"] == "promoter"

    def test_promoter_10(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([_resp(score=10)])
        assert results[0]["tier"] == "promoter"

    def test_passive_7(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([_resp(score=7)])
        assert results[0]["tier"] == "passive"

    def test_passive_8(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([_resp(score=8)])
        assert results[0]["tier"] == "passive"

    def test_detractor_6(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([_resp(score=6)])
        assert results[0]["tier"] == "detractor"

    def test_detractor_0(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([_resp(score=0)])
        assert results[0]["tier"] == "detractor"


class TestTagFormat:

    def test_tag_emitted(self):
        router = _ok_router()
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            apply_nps_tags([_resp(cid="c1", score=10)])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["nps:promoter"]
        assert params["id"] == "c1"


class TestDedup:

    def test_most_recent_wins(self):
        # Customer submits 9 first, then 3 -- second tag wins
        router = _ok_router()
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ):
            results = apply_nps_tags([
                _resp(cid="c1", score=9),
                _resp(cid="c1", score=3),
            ])
        # Only one Shopify call, one result
        assert router.execute.call_count == 1
        assert len(results) == 1
        assert results[0]["tier"] == "detractor"


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.nps_engine.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ) as record_mock:
            apply_nps_tags([_resp(cid="c1", score=10)])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "nps_engine"
        assert kw["action_type"] == "apply_nps_tags"
        assert kw["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "responses": [
                    {"customer_id": "c1", "score": 10},
                    {"customer_id": "c2", "score": 3},
                ],
                "segments": [],
                "apply_nps_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
        ) as apply_mock:
            result = NpsEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_nps"] == []

    def test_opt_in_invokes_applier(self):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
            return_value=[
                {
                    "customer_id": "c1", "tier": "promoter",
                    "score": 10, "applied": True, "error": None,
                },
            ],
        ) as apply_mock:
            result = NpsEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_nps"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = NpsEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_nps"] == []
