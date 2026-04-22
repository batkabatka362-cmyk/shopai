"""SupplierStep wire-up tests.

Previously a TODO stub that raised StepSkip. Now validates
the sourcing_id via CJ adapter's SOURCING_GET_PRODUCT
capability + records supplier metadata on context.supplier.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from workflows.launch.context import LaunchContext, LaunchGoal
from workflows.launch.steps._base import StepSkip
from workflows.launch.steps.supplier import SupplierStep


def _context(
    *,
    supplier_url: str = "https://cjdropshipping.com/prod/42",
    sourcing_id: str = "42",
) -> LaunchContext:
    goal = LaunchGoal()
    ctx = LaunchContext(
        goal=goal, launch_id="test_launch_supplier",
    )
    ctx.source = {
        "supplier_url": supplier_url,
        "sourcing_id": sourcing_id,
    }
    return ctx


class TestSupplierGating(unittest.TestCase):
    def test_no_key_raises_step_skip(self):
        with patch.dict(
            "os.environ",
            {
                "CJ_DROPSHIPPING_API_KEY": "",
                "AUTODS_API_KEY": "",
            },
            clear=False,
        ):
            step = SupplierStep()
            with self.assertRaises(StepSkip):
                step.execute(_context())

    def test_autods_only_skips_pending_adapter(self):
        with patch.dict(
            "os.environ",
            {
                "CJ_DROPSHIPPING_API_KEY": "",
                "AUTODS_API_KEY": "autods_xxx",
            },
            clear=False,
        ):
            step = SupplierStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(_context())
            self.assertIn(
                "AutoDS", str(ex.exception),
            )

    def test_no_source_info_skips(self):
        with patch.dict(
            "os.environ",
            {"CJ_DROPSHIPPING_API_KEY": "cj_xxx"},
            clear=False,
        ):
            step = SupplierStep()
            ctx = _context(supplier_url="", sourcing_id="")
            with self.assertRaises(StepSkip):
                step.execute(ctx)


class TestSupplierValidation(unittest.TestCase):
    def _mock_adapter(self, ok: bool = True):
        from core.adapters.base import AdapterResult

        adapter = MagicMock()
        adapter.is_configured.return_value = True
        if ok:
            adapter.execute.return_value = (
                AdapterResult.success(
                    adapter="cj_dropshipping",
                    capability="sourcing_get_product",
                    data={
                        "title": "Slow Feeder Bowl",
                        "price_usd": 4.50,
                    },
                    raw={},
                )
            )
        else:
            adapter.execute.return_value = (
                AdapterResult.failure(
                    adapter="cj_dropshipping",
                    capability="sourcing_get_product",
                    error="product not found",
                    raw={},
                )
            )
        return adapter

    def test_happy_path_records_validated_supplier(self):
        with patch.dict(
            "os.environ",
            {"CJ_DROPSHIPPING_API_KEY": "cj_xxx"},
            clear=False,
        ):
            adapter = self._mock_adapter(ok=True)
            with patch(
                "core.adapters.sourcing.cj_dropshipping."
                "CJDropshippingAdapter",
                return_value=adapter,
            ):
                step = SupplierStep()
                ctx = _context()
                out = step.execute(ctx)
        self.assertTrue(out["validated"])
        self.assertEqual(
            out["supplier_title"], "Slow Feeder Bowl",
        )
        self.assertAlmostEqual(
            out["supplier_cost_usd"], 4.50, places=2,
        )
        # Context stores same
        self.assertEqual(
            ctx.supplier["sourcing_id"], "42",
        )

    def test_adapter_failure_records_but_doesnt_raise(self):
        """Unknown sourcing_id shouldn't abort the launch —
        record the failure + continue. The order-handler
        retries per-order anyway."""
        with patch.dict(
            "os.environ",
            {"CJ_DROPSHIPPING_API_KEY": "cj_xxx"},
            clear=False,
        ):
            adapter = self._mock_adapter(ok=False)
            with patch(
                "core.adapters.sourcing.cj_dropshipping."
                "CJDropshippingAdapter",
                return_value=adapter,
            ):
                step = SupplierStep()
                out = step.execute(_context())
        self.assertFalse(out["validated"])
        self.assertIn("product not found", out["error"])

    def test_url_only_skips_validation_gracefully(self):
        """If source gave a URL but no sourcing_id we can't
        call get_product. Record the URL and move on."""
        with patch.dict(
            "os.environ",
            {"CJ_DROPSHIPPING_API_KEY": "cj_xxx"},
            clear=False,
        ):
            step = SupplierStep()
            ctx = _context(sourcing_id="")
            out = step.execute(ctx)
        self.assertFalse(out["validated"])
        self.assertEqual(out["sourcing_id"], "")
        self.assertIn("validation skipped", out["reason"])

    def test_unconfigured_adapter_skips(self):
        with patch.dict(
            "os.environ",
            {"CJ_DROPSHIPPING_API_KEY": "cj_xxx"},
            clear=False,
        ):
            adapter = MagicMock()
            adapter.is_configured.return_value = False
            with patch(
                "core.adapters.sourcing.cj_dropshipping."
                "CJDropshippingAdapter",
                return_value=adapter,
            ):
                step = SupplierStep()
                with self.assertRaises(StepSkip):
                    step.execute(_context())


if __name__ == "__main__":
    unittest.main()
