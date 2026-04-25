"""Dedup test: shipping_feasibility.billable_weight lives in
exactly one place.

Pre-refactor, ``_billable_weight`` was defined identically in
``code.py`` (19) and ``logic.py`` (15) — drift waiting to
happen. This test locks the single source of truth at
``utils.billable_weight`` and verifies both call sites import
from there.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


def _ast_top_level_funcs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
    }


class TestBillableWeightDedup(unittest.TestCase):
    def setUp(self):
        base = Path(
            "engines/product_filter/modules/"
            "shipping_feasibility",
        )
        self.utils_path = base / "utils.py"
        self.code_path = base / "code.py"
        self.logic_path = base / "logic.py"

    def test_utils_defines_billable_weight(self):
        funcs = _ast_top_level_funcs(self.utils_path)
        self.assertIn("billable_weight", funcs)

    def test_code_no_local_definition(self):
        funcs = _ast_top_level_funcs(self.code_path)
        self.assertNotIn(
            "_billable_weight", funcs,
            msg=(
                "code.py shouldn't redefine _billable_weight "
                "— import from .utils instead"
            ),
        )

    def test_logic_no_local_definition(self):
        funcs = _ast_top_level_funcs(self.logic_path)
        self.assertNotIn(
            "_billable_weight", funcs,
            msg=(
                "logic.py shouldn't redefine _billable_weight "
                "— import from .utils instead"
            ),
        )


class TestBillableWeightMath(unittest.TestCase):
    def test_actual_weight_wins_when_small_box(self):
        from engines.product_filter.modules.shipping_feasibility.utils import (
            billable_weight,
        )
        self.assertEqual(
            billable_weight(
                2.0, {"length": 10, "width": 10, "height": 10},
            ),
            2.0,
        )

    def test_dim_weight_wins_when_large_box(self):
        from engines.product_filter.modules.shipping_feasibility.utils import (
            billable_weight,
        )
        # vol = 100*50*30 = 150000; dim = 150000/5000 = 30kg
        self.assertEqual(
            billable_weight(
                1.0, {"length": 100, "width": 50, "height": 30},
            ),
            30.0,
        )

    def test_zero_dims_falls_back_to_actual(self):
        from engines.product_filter.modules.shipping_feasibility.utils import (
            billable_weight,
        )
        self.assertEqual(
            billable_weight(
                5.0, {"length": 0, "width": 0, "height": 0},
            ),
            5.0,
        )

    def test_non_dict_dims_does_not_crash(self):
        from engines.product_filter.modules.shipping_feasibility.utils import (
            billable_weight,
        )
        self.assertEqual(
            billable_weight(5.0, None),  # type: ignore[arg-type]
            5.0,
        )

    def test_custom_divisor(self):
        from engines.product_filter.modules.shipping_feasibility.utils import (
            billable_weight,
        )
        # vol = 60*40*20 = 48000; divisor 6000 → 8kg dim
        self.assertEqual(
            billable_weight(
                1.0,
                {"length": 60, "width": 40, "height": 20},
                divisor=6000,
            ),
            8.0,
        )


class TestEndToEndAfterDedup(unittest.TestCase):
    def test_check_shipping_feasibility_still_works(self):
        from engines.product_filter.modules.shipping_feasibility.code import (
            check_shipping_feasibility,
        )
        out = check_shipping_feasibility({
            "product": {
                "weight_kg": 1.5,
                "dimensions_cm": {
                    "length": 25, "width": 15, "height": 10,
                },
                "price": 40.0,
                "cost": 12.0,
            },
        })
        self.assertEqual(out["status"], "success")
        ev = out["data"]["evaluations"][0]["evaluation"]
        self.assertIn("billable_weight_kg", ev)
        self.assertGreater(ev["billable_weight_kg"], 0)

    def test_recommend_shipping_method_still_works(self):
        from engines.product_filter.modules.shipping_feasibility.logic import (
            recommend_shipping_method,
        )
        out = recommend_shipping_method({
            "weight_kg": 1.0,
            "dimensions_cm": {
                "length": 30, "width": 20, "height": 10,
            },
            "is_international": False,
        })
        self.assertIn("billable_weight_kg", out)
        self.assertIn("carrier", out)


if __name__ == "__main__":
    unittest.main()
