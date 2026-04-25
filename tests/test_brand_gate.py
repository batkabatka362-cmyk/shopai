"""Brand pre-ship gate + PublisherBundle wire-up."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.brand import (
    BrandGateRejected,
    brand_gate,
    reload_brand_rules,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reload_brand_rules()
    yield
    reload_brand_rules()


_CALM_METAFIELDS = [{
    "namespace": "shopai",
    "key": "brand",
    "value": json.dumps({
        "voice": "calm_cozy",
        "forbidden_words": ["competitor"],
        "tagline": "Calm & cozy living",
    }),
}]


class TestModes:
    def test_reject_raises_on_errors(self):
        with pytest.raises(BrandGateRejected) as exc:
            brand_gate(
                text="CRAZY deal on lamps",
                surface="ad_copy",
                mode="reject",
                metafields=_CALM_METAFIELDS,
            )
        assert exc.value.check.surface == "ad_copy"
        assert len(exc.value.check.errors) >= 1

    def test_reject_passes_clean_content(self):
        verdict = brand_gate(
            text="Soft, warm glow for quiet evenings.",
            surface="ad_copy",
            mode="reject",
            metafields=_CALM_METAFIELDS,
        )
        assert verdict.passed
        assert verdict.errors == ()

    def test_warn_never_raises(self):
        verdict = brand_gate(
            text="CRAZY deal on lamps",
            surface="ad_copy",
            mode="warn",
            metafields=_CALM_METAFIELDS,
        )
        assert not verdict.passed
        # errors populated for the caller to inspect.
        assert len(verdict.errors) >= 1

    def test_log_never_raises(self):
        verdict = brand_gate(
            text="CRAZY deal on lamps",
            surface="ad_copy",
            mode="log",
            metafields=_CALM_METAFIELDS,
        )
        assert not verdict.passed

    def test_bad_mode_raises(self):
        with pytest.raises(ValueError):
            brand_gate(
                text="x",
                surface="ad_copy",
                mode="nope",
                metafields=_CALM_METAFIELDS,
            )

    def test_trace_id_round_trips(self):
        verdict = brand_gate(
            text="cozy soft glow",
            surface="ad_copy",
            mode="warn",
            trace_id="campaign-99",
            metafields=_CALM_METAFIELDS,
        )
        assert verdict.trace_id == "campaign-99"
        dumped = json.dumps(verdict.as_dict())
        assert "campaign-99" in dumped


class TestCaching:
    def test_guard_memoised_across_calls(self):
        """Calls without an explicit metafields arg share
        the cached guard — fetch_live_metafields is only
        invoked once."""
        from core.brand import pre_ship
        with patch.object(
            pre_ship, "_load_brand_metafields",
            return_value=[],
        ) as fake_load:
            brand_gate(
                text="hi", surface="ad_copy", mode="log",
            )
            brand_gate(
                text="hello", surface="ad_copy", mode="log",
            )
        assert fake_load.call_count == 1

    def test_reload_resets_cache(self):
        from core.brand import pre_ship
        with patch.object(
            pre_ship, "_load_brand_metafields",
            return_value=[],
        ) as fake_load:
            brand_gate(
                text="hi", surface="ad_copy", mode="log",
            )
            reload_brand_rules()
            brand_gate(
                text="hi", surface="ad_copy", mode="log",
            )
        assert fake_load.call_count == 2

    def test_explicit_metafields_bypass_cache(self):
        """Passing metafields directly must not pollute the
        session cache."""
        from core.brand import pre_ship
        with patch.object(
            pre_ship, "_load_brand_metafields",
            return_value=[],
        ) as fake_load:
            brand_gate(
                text="hi",
                surface="ad_copy",
                mode="log",
                metafields=_CALM_METAFIELDS,
            )
            # Second call still fetches live.
            brand_gate(
                text="hi", surface="ad_copy", mode="log",
            )
        # Explicit-metafields call did not trigger _load_...;
        # only the second (no explicit) call did.
        assert fake_load.call_count == 1


class TestPublisherBundleWire:
    def test_warn_mode_does_not_block_publisher(self):
        """The publisher's gate helper must never propagate
        exceptions — even if the underlying gate raises
        unexpectedly."""
        from execution.launch.publisher_bundle import (
            PublisherBundle,
        )

        # Use a minimal stub request (no winner fields needed
        # beyond attribute access).
        class _Winner:
            product_id = "P-1"

        class _Req:
            platform = "meta"
            winner = _Winner()

        b = PublisherBundle()
        # Force brand_gate to raise — helper should swallow.
        with patch(
            "core.brand.brand_gate",
            side_effect=RuntimeError("kaboom"),
        ):
            out = b._brand_gate_ad_copy(
                {"body": "cozy lamp copy"}, request=_Req(),
            )
        assert out is None

    def test_gate_returns_verdict_dict(self):
        from execution.launch.publisher_bundle import (
            PublisherBundle,
        )

        class _Winner:
            product_id = "P-1"

        class _Req:
            platform = "meta"
            winner = _Winner()

        b = PublisherBundle()
        with patch(
            "core.brand.pre_ship._load_brand_metafields",
            return_value=_CALM_METAFIELDS,
        ):
            reload_brand_rules()  # pick up the patched loader
            out = b._brand_gate_ad_copy(
                {"body": "soft cozy glow for you"},
                request=_Req(),
            )
        assert isinstance(out, dict)
        assert out["surface"] == "ad_copy"
        assert out["passed"] is True
        # trace_id surfaces the platform + product id.
        assert "meta" in out["trace_id"]
        assert "P-1" in out["trace_id"]

    def test_empty_body_skips_gate(self):
        from execution.launch.publisher_bundle import (
            PublisherBundle,
        )

        class _Winner:
            product_id = ""

        class _Req:
            platform = "meta"
            winner = _Winner()

        b = PublisherBundle()
        out = b._brand_gate_ad_copy({}, request=_Req())
        assert out is None
