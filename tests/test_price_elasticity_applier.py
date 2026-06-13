"""Tests for engines.price_elasticity.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.price_elasticity.tag_applier import apply_elasticity_tags


def _ela(pid="p1", coef=-1.5, is_elastic=True, **extra):
    return {
        "product_id": pid,
        "coefficient": coef,
        "is_elastic": is_elastic,
        **extra,
    }


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestTagComposition:

    def test_elastic_only_below_highly(self):
        router = _ok_router("p1")
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ):
            apply_elasticity_tags(
                [_ela(coef=-1.5)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "pricing:elastic" in params["tags"]
        assert "pricing:highly_elastic" not in params["tags"]
        assert "pricing:inelastic" not in params["tags"]

    def test_highly_elastic_above_threshold(self):
        router = _ok_router("p1")
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ):
            apply_elasticity_tags(
                [_ela(coef=-2.5)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "pricing:elastic" in params["tags"]
        assert "pricing:highly_elastic" in params["tags"]

    def test_inelastic_when_coef_le_one(self):
        router = _ok_router("p1")
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ):
            apply_elasticity_tags(
                [_ela(coef=-0.5, is_elastic=False)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "pricing:inelastic" in params["tags"]
        assert "pricing:elastic" not in params["tags"]

    def test_positive_coef_also_works(self):
        # In rare cases, coefficient may be positive (luxury/Veblen
        # goods). |coef| is what matters.
        router = _ok_router("p1")
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ):
            apply_elasticity_tags(
                [_ela(coef=1.5, is_elastic=True)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "pricing:elastic" in params["tags"]


class TestSkipZero:

    def test_zero_coef_skipped(self):
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ):
            results = apply_elasticity_tags(
                [_ela(coef=0.0)],
                [_product("p1")],
            )
        assert results == []


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ):
            apply_elasticity_tags(
                [_ela(coef=-1.5)],
                [_product("p1", tags=["best_seller"])],
            )
        params = router.execute.call_args.args[1]
        assert "best_seller" in params["tags"]
        assert "pricing:elastic" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.price_elasticity.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.price_elasticity.tag_applier.record_writeback",
        ) as record_mock:
            apply_elasticity_tags(
                [_ela(coef=-1.5)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "price_elasticity"
        assert kw["action_type"] == "apply_elasticity_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {"id": "p1", "title": "Widget", "tags": [], "price": 50},
                ],
                "price_history": [
                    {"product_id": "p1", "price": 40, "date": "2026-04-01"},
                    {"product_id": "p1", "price": 50, "date": "2026-05-01"},
                ],
                "sales_data": [
                    {"product_id": "p1", "quantity": 100, "date": "2026-04-01"},
                    {"product_id": "p1", "quantity": 80, "date": "2026-05-01"},
                ],
                "apply_elasticity_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.price_elasticity.flow import PriceElasticityEngine
        with patch(
            "engines.price_elasticity.tag_applier.apply_elasticity_tags",
        ) as apply_mock:
            result = PriceElasticityEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_elasticity"] == []

    def test_opt_in_invokes_applier(self):
        from engines.price_elasticity.flow import PriceElasticityEngine
        with patch(
            "engines.price_elasticity.tag_applier.apply_elasticity_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "coefficient": -1.5, "error": None,
                },
            ],
        ) as apply_mock:
            result = PriceElasticityEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_elasticity"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.price_elasticity.flow import PriceElasticityEngine
        with patch(
            "engines.price_elasticity.tag_applier.apply_elasticity_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = PriceElasticityEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_elasticity"] == []
