"""SourceStep supplier_sku wire tests.

Previously a TODO stub raised StepSkip for every supplier_sku
lookup. This batch wires it to CJDropshippingAdapter.
SOURCING_GET_PRODUCT + normalises the response into the
source-agnostic shape downstream steps expect.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from workflows.launch.context import LaunchContext, LaunchGoal
from workflows.launch.steps._base import StepSkip
from workflows.launch.steps.source import SourceStep


def _context(sourcing_id: str = "42") -> LaunchContext:
    goal = LaunchGoal(supplier_sku=sourcing_id)
    return LaunchContext(
        goal=goal, launch_id="test_source_sku",
    )


class TestSupplierSkuGating(unittest.TestCase):
    def test_empty_sku_skips(self):
        step = SourceStep()
        with self.assertRaises(StepSkip) as ex:
            step.execute(_context(sourcing_id=""))
        self.assertTrue(ex.exception)

    def test_unconfigured_adapter_skips(self):
        adapter = MagicMock()
        adapter.is_configured.return_value = False
        with patch(
            "core.adapters.sourcing.cj_dropshipping."
            "CJDropshippingAdapter",
            return_value=adapter,
        ):
            step = SourceStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(_context())
            self.assertIn(
                "CJ adapter not configured",
                str(ex.exception),
            )

    def test_adapter_failure_skips_with_reason(self):
        from core.adapters.base import AdapterResult

        adapter = MagicMock()
        adapter.is_configured.return_value = True
        adapter.execute.return_value = AdapterResult.failure(
            adapter="cj_dropshipping",
            capability="sourcing_get_product",
            error="product not found",
            raw={},
        )
        with patch(
            "core.adapters.sourcing.cj_dropshipping."
            "CJDropshippingAdapter",
            return_value=adapter,
        ):
            step = SourceStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(_context(sourcing_id="999"))
            self.assertIn(
                "product not found",
                str(ex.exception),
            )
            self.assertIn("999", str(ex.exception))

    def test_empty_title_skips(self):
        """CJ sometimes returns partial records — no title is
        a useless result, so skip rather than downstream-fail."""
        from core.adapters.base import AdapterResult

        adapter = MagicMock()
        adapter.is_configured.return_value = True
        adapter.execute.return_value = AdapterResult.success(
            adapter="cj_dropshipping",
            capability="sourcing_get_product",
            data={"title": "", "price_usd": 5.0},
            raw={},
        )
        with patch(
            "core.adapters.sourcing.cj_dropshipping."
            "CJDropshippingAdapter",
            return_value=adapter,
        ):
            step = SourceStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(_context())
            self.assertIn("no title", str(ex.exception))


class TestSupplierSkuHappyPath(unittest.TestCase):
    def _install_adapter(
        self,
        *,
        title: str = "Pet Slow-Feeder Bowl",
        price_usd: float = 4.50,
        supplier_url: str = "",
        gallery_urls: list | None = None,
        attributes: dict | None = None,
    ):
        from core.adapters.base import AdapterResult

        adapter = MagicMock()
        adapter.is_configured.return_value = True
        data = {
            "title": title,
            "price_usd": price_usd,
        }
        if supplier_url:
            data["supplier_url"] = supplier_url
        if gallery_urls is not None:
            data["gallery_urls"] = gallery_urls
        if attributes is not None:
            data["attributes"] = attributes
        adapter.execute.return_value = AdapterResult.success(
            adapter="cj_dropshipping",
            capability="sourcing_get_product",
            data=data,
            raw={},
        )
        return adapter

    def test_happy_path_normalised_shape(self):
        adapter = self._install_adapter(
            title="Slow Feeder Bowl",
            price_usd=4.50,
            supplier_url="https://cj/prod/42",
            gallery_urls=["a.jpg", "b.jpg"],
            attributes={"color": "blue"},
        )
        with patch(
            "core.adapters.sourcing.cj_dropshipping."
            "CJDropshippingAdapter",
            return_value=adapter,
        ):
            step = SourceStep()
            out = step.execute(_context(sourcing_id="42"))
        self.assertEqual(out["title"], "Slow Feeder Bowl")
        self.assertAlmostEqual(out["price_usd"], 4.50)
        self.assertEqual(
            out["supplier_url"], "https://cj/prod/42",
        )
        self.assertEqual(
            out["gallery_urls"], ["a.jpg", "b.jpg"],
        )
        self.assertEqual(
            out["attributes"], {"color": "blue"},
        )
        self.assertEqual(out["sourcing_id"], "42")
        self.assertEqual(
            out["_source_kind"], "supplier_sku",
        )

    def test_missing_supplier_url_falls_back_to_cj_scheme(self):
        adapter = self._install_adapter(
            title="Widget", price_usd=3.0,
        )
        with patch(
            "core.adapters.sourcing.cj_dropshipping."
            "CJDropshippingAdapter",
            return_value=adapter,
        ):
            step = SourceStep()
            out = step.execute(_context(sourcing_id="77"))
        self.assertEqual(
            out["supplier_url"], "cj://product/77",
        )

    def test_adapter_called_with_correct_sourcing_id(self):
        adapter = self._install_adapter()
        with patch(
            "core.adapters.sourcing.cj_dropshipping."
            "CJDropshippingAdapter",
            return_value=adapter,
        ):
            step = SourceStep()
            step.execute(_context(sourcing_id="abc123"))
        call_args = adapter.execute.call_args
        params = call_args[0][1]
        self.assertEqual(params["sourcing_id"], "abc123")


if __name__ == "__main__":
    unittest.main()
