"""Tests for audit-pass-36 fixes — defensive hardening across
all 7 domain agent evaluators (product, marketing, content,
finance, operations, customer, research).

Each evaluator had the same anti-patterns:

  1. ``results.get("engine_results", {})`` / ``completed_steps``
     / ``total_steps`` with no guard on ``results`` itself —
     None ``results`` crashed the very first line with
     AttributeError.

  2. ``results.get("completed_steps", 0)`` returns the
     default only when the key is MISSING; present-but-None
     crashed the ``completed / max(total, 1)`` math later.

  3. ``engine_result.get("data", {}).get(...)`` — present-but-
     None ``data`` field crashed the chained ``.get``. 60
     instances across the 7 files.

  4. ``results.get("engine_name", {})`` followed by
     ``.get("status")`` — if someone passed a non-dict engine
     result (e.g. a bare list or string from a buggy stub)
     the chained call crashed. The entry-level coercion now
     ensures ``engine_results`` is a dict, but the per-engine
     value can still be non-dict; the helper score functions
     silently skip those cases because ``.get("status")`` on a
     non-dict raises AttributeError.

The fix pattern is identical in all 7 files, so this audit
pass uses parametrized tests that drive each evaluator through
the same set of malformed / hostile inputs.
"""
import importlib

import pytest


EVALUATOR_MODULES = [
    "agents.product.evaluator",
    "agents.marketing.evaluator",
    "agents.content.evaluator",
    "agents.finance.evaluator",
    "agents.operations.evaluator",
    "agents.customer.evaluator",
    "agents.research.evaluator",
]


# ── Defensive caller-arg coercion ───────────────────────────


@pytest.mark.parametrize("module_path", EVALUATOR_MODULES)
class TestDefensiveCallerArgs:
    def test_none_results_does_not_crash(self, module_path):
        """Regression: ``results.get`` used to crash with
        AttributeError when ``results`` was None."""
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(results=None, goal="test")
        assert isinstance(report, dict)
        assert "score" in report
        assert 0 <= report["score"] <= 100

    def test_none_goal_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(results={}, goal=None)
        assert isinstance(report, dict)

    def test_non_dict_results_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(results="not a dict", goal="test")
        assert isinstance(report, dict)

    def test_none_completed_steps_does_not_crash(self, module_path):
        """Regression: ``results.get("completed_steps", 0)``
        returns the default only when the key is missing —
        present-but-None used to crash the int math."""
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(
            results={
                "engine_results": {},
                "completed_steps": None,
                "total_steps": None,
            },
            goal="test",
        )
        assert isinstance(report, dict)
        assert "score" in report

    def test_non_numeric_total_steps_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(
            results={
                "engine_results": {},
                "completed_steps": "not a number",
                "total_steps": "also not",
            },
            goal="test",
        )
        assert isinstance(report, dict)


# ── Present-but-None data field in engine results ───────────


@pytest.mark.parametrize("module_path", EVALUATOR_MODULES)
class TestPresentButNoneData:
    def test_engine_with_none_data_field_does_not_crash(self, module_path):
        """Regression: ``engine_result.get("data", {})`` returns
        ``{}`` only when the key is missing — present-but-None
        crashed the chained ``.get`` call. 60 instances fixed
        in audit pass 36."""
        mod = importlib.import_module(module_path)

        # Build an engine_results dict where every plausible
        # engine name has ``{"status": "success", "data": None}``.
        # This is the shape an upstream executor could legitimately
        # produce if an engine returned ``{"status": "success"}``
        # without a ``data`` key (json.loads can also yield None
        # for an explicit null value in some serialisations).
        probable_engine_names = [
            # Product
            "product_filter", "product_scoring", "product_validation",
            "product_ranking", "pricing", "profitability_calculator",
            "product_risk", "catalog",
            # Marketing
            "content_generation", "email_marketing", "social_media",
            "ab_testing", "influencer", "affiliate", "landing_page",
            "video_marketing",
            # Content
            "product_description", "search_optimization",
            "image_optimization", "tag_management",
            # Finance
            "financial", "forecasting", "kpi_tracking", "price_elasticity",
            "discount_strategy", "dynamic_pricing", "profit_optimization",
            # Operations
            "inventory", "stock_prediction", "supplier",
            "supplier_discovery", "shipping_optimization",
            "returns_management",
            # Customer
            "customer_segmentation", "churn_prediction",
            "sentiment_analysis", "review_management",
            "customer_support", "chatbot", "audience_targeting",
            # Research
            "market_research", "trend_discovery",
        ]
        engine_results = {
            name: {"status": "success", "data": None, "error": None}
            for name in probable_engine_names
        }

        report = mod.evaluate_results(
            results={
                "engine_results": engine_results,
                "completed_steps": len(probable_engine_names),
                "total_steps": len(probable_engine_names),
            },
            goal="test",
        )
        assert isinstance(report, dict)
        assert "score" in report

    def test_engine_with_non_dict_result_does_not_crash(self, module_path):
        """Regression: a non-dict engine result (e.g. a raw
        string or list from a buggy engine stub) used to crash
        the helper score functions on ``.get("status")``.
        Non-dict values are now silently skipped."""
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(
            results={
                "engine_results": {
                    "some_engine": "a raw string instead of a dict",
                    "other_engine": ["list", "instead", "of", "dict"],
                    "null_engine": None,
                },
                "completed_steps": 0,
                "total_steps": 3,
            },
            goal="test",
        )
        assert isinstance(report, dict)


# ── Non-dict engine_results bag ─────────────────────────────


@pytest.mark.parametrize("module_path", EVALUATOR_MODULES)
class TestNonDictEngineResults:
    def test_none_engine_results_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(
            results={
                "engine_results": None,
                "completed_steps": 0,
                "total_steps": 0,
            },
            goal="test",
        )
        assert isinstance(report, dict)

    def test_list_engine_results_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        report = mod.evaluate_results(
            results={
                "engine_results": ["not", "a", "dict"],
                "completed_steps": 0,
                "total_steps": 0,
            },
            goal="test",
        )
        assert isinstance(report, dict)
