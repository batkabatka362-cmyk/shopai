"""Tests for ``engines.store_setup.customer_segments``.

Generator produces structured segment specs; applier pushes
each via ``SHOPIFY_CREATE_SEGMENT`` and records via
Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: 7 universal segments always present.
  3. Generator: niche-specific stack on top of universal.
  4. Generator: every niche has full segment shape (name +
     query + rationale + engines list).
  5. Generator: every shipped niche resolves (no KeyError).
  6. Generator: unknown niche falls back to general
     (universal-only).
  7. Generator: ShopifyQL queries are well-formed strings.
  8. Applier: empty / non-list segments -> short-circuit.
  9. Applier: router_unavailable + per-segment failure
     recording.
 10. Applier: missing name OR query skipped per-segment.
 11. Applier: success path + Pattern Z per segment.
 12. Applier: per-segment failure isolation (one rejection
     doesn't block others).
 13. Applier: adapter raise captured per segment.
 14. Applier: segment_id captured on success.
 15. store_id propagation per segment.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.customer_segments import (
    _NICHE_SEGMENTS,
    _UNIVERSAL_SEGMENTS,
    apply_segment_pack,
    generate_segment_pack,
)


def _ok(data=None):
    return SimpleNamespace(
        ok=True, data=data or {}, error=None,
    )


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_segment_pack(store_name="") == {}
        assert (
            generate_segment_pack(store_name="   ") == {}
        )
        assert (
            generate_segment_pack(store_name=None) == {}
        )


class TestGeneratorShape:

    def test_universal_segments_always_present(self):
        spec = generate_segment_pack(
            store_name="Acme", niche="general",
        )
        # General niche has empty niche-specific list, so
        # total == universal count.
        assert (
            len(spec["segments"])
            == len(_UNIVERSAL_SEGMENTS)
        )
        # First-N entries are the universal set in order
        for i, entry in enumerate(_UNIVERSAL_SEGMENTS):
            seg = spec["segments"][i]
            assert seg["name"] == entry[0]
            assert seg["query"] == entry[1]
            assert seg["rationale"] == entry[2]

    def test_niche_stacks_on_universal(self):
        spec = generate_segment_pack(
            store_name="Acme", niche="beauty",
        )
        # Beauty has 2 niche-specific
        assert (
            len(spec["segments"])
            == len(_UNIVERSAL_SEGMENTS) + 2
        )

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_segment_pack(
            store_name="Acme", niche="ufo_parts",
        )
        # General-only -> universal count
        assert (
            len(spec["segments"])
            == len(_UNIVERSAL_SEGMENTS)
        )

    def test_every_segment_has_full_shape(self):
        for niche in _NICHE_SEGMENTS:
            spec = generate_segment_pack(
                store_name="Acme", niche=niche,
            )
            for seg in spec["segments"]:
                assert seg["name"], niche
                assert seg["query"], niche
                assert seg["rationale"], niche
                assert isinstance(seg["engines"], list)
                assert len(seg["engines"]) >= 1, niche

    def test_every_niche_resolves(self):
        """No KeyError on any niche."""
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_segment_pack(
                store_name="Acme", niche=niche,
            )
            assert spec["segments"]


class TestQuerySanity:

    def test_no_blank_queries(self):
        for niche in _NICHE_SEGMENTS:
            spec = generate_segment_pack(
                store_name="Acme", niche=niche,
            )
            for seg in spec["segments"]:
                assert seg["query"].strip()
                # ShopifyQL syntax sanity: at least one
                # operator (=, >, <, CONTAINS).
                q = seg["query"]
                assert any(
                    op in q
                    for op in ("=", ">", "<", "CONTAINS")
                ), niche

    def test_engine_names_known(self):
        """Every engine listed in a segment's `engines`
        field must be one we actually ship."""
        valid_engines = {
            "loyalty", "churn_prediction",
            "email_marketing", "dynamic_pricing",
            "wholesale_b2b",
        }
        for niche in _NICHE_SEGMENTS:
            spec = generate_segment_pack(
                store_name="Acme", niche=niche,
            )
            for seg in spec["segments"]:
                for engine in seg["engines"]:
                    assert engine in valid_engines, (
                        niche, seg["name"], engine,
                    )


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_non_dict_input(self):
        out = apply_segment_pack(None)  # type: ignore[arg-type]
        assert out["applied_count"] == 0

    def test_empty_spec(self):
        out = apply_segment_pack({})
        assert out["applied_count"] == 0

    def test_spec_without_segments(self):
        out = apply_segment_pack({"store_name": "Acme"})
        assert out["applied_count"] == 0


class TestApplierRouterFailure:

    def test_router_unavailable(self):
        spec = generate_segment_pack(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ) as record_mock:
            out = apply_segment_pack(spec)
        assert out["applied_count"] == 0
        # All segments recorded as failures
        assert (
            record_mock.call_count == len(spec["segments"])
        )


class TestApplierSuccess:

    def test_all_segments_applied(self):
        router = MagicMock()
        ids = iter([f"gid://s/{i}" for i in range(20)])

        def _exec(cap, params):
            return _ok({"segment": {"id": next(ids)}})

        router.execute.side_effect = _exec
        spec = generate_segment_pack(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ) as record_mock:
            out = apply_segment_pack(spec)
        assert out["applied_count"] == len(spec["segments"])
        for r in out["results"]:
            assert r["ok"] is True
            assert r["segment_id"]
            assert r["error"] is None
        # Pattern Z called once per segment
        assert (
            record_mock.call_count == len(spec["segments"])
        )

    def test_params_forwarded(self):
        """name + query forwarded to the adapter call."""
        router = MagicMock()
        captured: list[dict] = []

        def _exec(cap, params):
            captured.append(params)
            return _ok({"segment": {"id": "gid://s/1"}})

        router.execute.side_effect = _exec
        spec = generate_segment_pack(
            store_name="Acme", niche="general",
        )
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ):
            apply_segment_pack(spec)
        # Each captured call has the expected shape
        for params, seg in zip(captured, spec["segments"]):
            assert params["name"] == seg["name"]
            assert params["query"] == seg["query"]


class TestApplierFailureIsolation:

    def test_partial_failure(self):
        router = MagicMock()

        def _exec(cap, params):
            if params["name"] == "At-Risk (60d)":
                return _fail("duplicate name")
            return _ok({"segment": {"id": "gid://s/1"}})

        router.execute.side_effect = _exec
        spec = generate_segment_pack(
            store_name="Acme", niche="general",
        )
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ):
            out = apply_segment_pack(spec)
        # 1 failure -> applied_count = total - 1
        assert (
            out["applied_count"]
            == len(spec["segments"]) - 1
        )
        # The failing one carries the error
        bad = next(
            r for r in out["results"]
            if r["name"] == "At-Risk (60d)"
        )
        assert bad["ok"] is False
        assert "duplicate name" in bad["error"]

    def test_adapter_raise_isolates(self):
        router = MagicMock()
        call_count = {"i": 0}

        def _exec(cap, params):
            call_count["i"] += 1
            if call_count["i"] == 3:
                raise RuntimeError("network")
            return _ok({"segment": {"id": "gid://s/1"}})

        router.execute.side_effect = _exec
        spec = generate_segment_pack(
            store_name="Acme", niche="general",
        )
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ):
            out = apply_segment_pack(spec)
        # 1 raised -> applied_count = total - 1
        assert (
            out["applied_count"]
            == len(spec["segments"]) - 1
        )
        raised = [r for r in out["results"] if not r["ok"]]
        assert len(raised) == 1
        assert "network" in raised[0]["error"]

    def test_missing_name_or_query_skipped(self):
        router = MagicMock()
        router.execute.return_value = _ok(
            {"segment": {"id": "gid://s/1"}},
        )
        spec = {
            "store_name": "Acme",
            "niche": "general",
            "segments": [
                {"name": "", "query": "x = 1"},
                {"name": "OK", "query": ""},
                {
                    "name": "Good",
                    "query": "amount_spent > 100",
                    "engines": [],
                },
            ],
        }
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ):
            out = apply_segment_pack(spec)
        # Only the third one applies
        assert out["applied_count"] == 1
        # First two skipped with missing_name_or_query
        assert (
            out["results"][0]["error"]
            == "missing_name_or_query"
        )
        assert (
            out["results"][1]["error"]
            == "missing_name_or_query"
        )


# ── store_id propagation ─────────────────────────────────────


class TestStoreIdPropagation:

    def test_store_id_recorded_per_segment(self):
        router = MagicMock()
        router.execute.return_value = _ok(
            {"segment": {"id": "gid://s/1"}},
        )
        spec = generate_segment_pack(
            store_name="Acme", niche="general",
        )
        with patch(
            "engines.store_setup.customer_segments."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.customer_segments."
            "record_writeback",
        ) as record_mock:
            apply_segment_pack(spec, store_id="store-a")
        assert (
            record_mock.call_count == len(spec["segments"])
        )
        for call in record_mock.call_args_list:
            assert (
                call.kwargs["params"]["store_id"]
                == "store-a"
            )
