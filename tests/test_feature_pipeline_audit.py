"""Tests for audit-pass-50 fixes — defensive hardening across
the final data_pipeline layers (feature_engineering + pipelines).

Real bugs fixed:

  * feature_builder.build_price_features / _engagement /
    _trend all used bare ``float(record.get("field") or 0)``
    which crashed on currency strings and other non-numeric
    values from the upstream cleaning/normalisation path.

  * feature_builder.build_features did ``[dict(r) for r in data]``
    without a None-data guard, and ``dict(record)`` inside
    the loop without a non-dict guard.

  * feature_builder.build_trend_features did
    ``[float(item.get("value", 0) or 0) for item in time_series]``
    which crashed on non-dict items in the list.

  * feature_selector.select read ``selection_config.get(...)``
    without a non-dict guard; None config crashed.

  * feature_selector.select cast ``float(threshold)`` and
    ``int(k)`` directly — non-numeric config values crashed.

  * feature_selector.calculate_feature_importance did bare
    ``float(r.get(target, 0) or 0)`` which crashed on
    non-numeric target values (ad-platform revenue often
    comes back as a string).

  * feature_store._MEMORY_CACHE dict reads/writes had no
    lock. Concurrent ``store()`` calls could race.

  * feature_store._validate_name did ``re.match(regex, name)``
    directly — if ``name`` was None or non-string, ``re.match``
    raised ``TypeError`` instead of the documented
    ``FeatureStoreError``.

  * feature_store.delete did not validate the name, so a
    caller passing ``"../etc/passwd"`` could attempt to
    delete arbitrary files (the regex in ``_validate_name``
    blocks path traversal, but ``delete`` never called it).

  * All three pipelines (analytics, marketing, product) did
    ``len(raw_data)`` on the first line before any coercion
    — None input crashed before reaching the defensively-
    hardened ``DataCleaner.clean()``.

  * Pipeline metric computers (_compute_analytics_metrics,
    _compute_ad_metrics) used bare ``float()`` on record
    fields — same crash-on-currency-string bug as the
    feature builder.
"""
from __future__ import annotations

import tempfile
import threading

import pytest

from data_pipeline.feature_engineering.feature_builder import FeatureBuilder
from data_pipeline.feature_engineering.feature_selector import FeatureSelector
from data_pipeline.feature_engineering.feature_store import (
    FeatureStore,
    FeatureStoreError,
)
from data_pipeline.pipelines.analytics_pipeline import (
    AnalyticsPipeline,
    _compute_analytics_metrics,
)
from data_pipeline.pipelines.marketing_pipeline import (
    MarketingPipeline,
    _compute_ad_metrics,
)
from data_pipeline.pipelines.product_pipeline import ProductPipeline


# ═══════════════════════════════════════════════════════════
# FeatureBuilder
# ═══════════════════════════════════════════════════════════


class TestFeatureBuilderDefensive:
    def test_build_features_none(self):
        fb = FeatureBuilder()
        assert fb.build_features(None) == []

    def test_build_features_non_list(self):
        fb = FeatureBuilder()
        assert fb.build_features("not a list") == []

    def test_build_features_mixed_list(self):
        fb = FeatureBuilder()
        result = fb.build_features(
            [None, "bad", 42, {"price": 100}],
            [{"type": "price"}],
        )
        assert len(result) == 1
        assert "price_features" in result[0]

    def test_build_features_non_dict_cfg(self):
        fb = FeatureBuilder()
        result = fb.build_features(
            [{"price": 100}],
            ["not a dict", None, {"type": "price"}],
        )
        assert len(result) == 1
        assert "price_features" in result[0]

    def test_build_features_none_config(self):
        fb = FeatureBuilder()
        result = fb.build_features([{"a": 1}], None)
        assert result == [{"a": 1}]


class TestFeatureBuilderPrice:
    def test_currency_string_price(self):
        """Regression: bare float("$99.99") crashed."""
        fb = FeatureBuilder()
        result = fb.build_price_features({
            "price": "$99.99", "cost": "$50.00", "compare_at": "$129.99",
        })
        assert result["price_tier"] == "mid"
        assert result["is_on_sale"] is True
        assert 0.0 < result["discount_depth"] < 1.0

    def test_none_product(self):
        assert FeatureBuilder().build_price_features(None)["margin_pct"] == 0.0

    def test_non_dict_product(self):
        assert FeatureBuilder().build_price_features("bad")["margin_pct"] == 0.0


class TestFeatureBuilderEngagement:
    def test_currency_monetary(self):
        fb = FeatureBuilder()
        result = fb.build_engagement_features({
            "days_since_last_order": "30",
            "order_count": "5",
            "total_spent": "$1,234.56",
        })
        assert result["monetary"] == 1234.56
        assert result["frequency"] == 5.0

    def test_empty_avg_order_value_fallback(self):
        """Pre-audit ``float(user_data.get("avg_order_value") or
        ...)`` evaluated the fallback for empty-string AOV;
        that path still works with safe_float."""
        fb = FeatureBuilder()
        result = fb.build_engagement_features({
            "order_count": 5, "total_spent": 500,
        })
        assert result["avg_order_value"] == 100.0

    def test_none_user(self):
        assert FeatureBuilder().build_engagement_features(None)["monetary"] == 0.0


class TestFeatureBuilderTrend:
    def test_non_dict_items_skipped(self):
        """Regression: pre-audit ``[float(item.get(...)) for ...]``
        crashed on non-dict items."""
        fb = FeatureBuilder()
        result = fb.build_trend_features([
            None,
            "bad",
            42,
            {"value": 50},
            {"value": "60"},  # string numeric
            {"value": 70},
        ])
        assert result["n"] == 3
        assert result["trend"] == "up"

    def test_currency_values(self):
        fb = FeatureBuilder()
        result = fb.build_trend_features([
            {"value": "$50"},
            {"value": "$60"},
            {"value": "$70"},
        ])
        assert result["n"] == 3
        assert result["trend"] == "up"

    def test_none_series(self):
        assert FeatureBuilder().build_trend_features(None)["n"] == 0

    def test_non_list_series(self):
        assert FeatureBuilder().build_trend_features("bad")["n"] == 0

    def test_empty_after_filtering(self):
        fb = FeatureBuilder()
        result = fb.build_trend_features(["bad", None, 42])
        assert result["n"] == 0


# ═══════════════════════════════════════════════════════════
# FeatureSelector
# ═══════════════════════════════════════════════════════════


class TestFeatureSelectorDefensive:
    def test_none_features(self):
        fs = FeatureSelector()
        assert fs.select(None, {"strategy": "variance"}) == []

    def test_none_config(self):
        fs = FeatureSelector()
        result = fs.select([{"a": 1}], None)
        assert result == [{"a": 1}]

    def test_non_dict_config(self):
        fs = FeatureSelector()
        result = fs.select([{"a": 1}], "not a dict")
        assert result == [{"a": 1}]

    def test_non_numeric_threshold(self):
        """Regression: pre-audit ``float(config.get("threshold"))``
        crashed on a non-numeric config."""
        fs = FeatureSelector()
        result = fs.select(
            [{"a": 1, "b": 2}, {"a": 1, "b": 3}],
            {"strategy": "variance", "threshold": "bad"},
        )
        assert isinstance(result, list)

    def test_non_int_k(self):
        fs = FeatureSelector()
        result = fs.select(
            [{"a": 1, "score": 5}, {"a": 2, "score": 3}],
            {"strategy": "top_k", "k": "bad", "score_field": "score"},
        )
        assert isinstance(result, list)

    def test_non_list_keep_fields(self):
        fs = FeatureSelector()
        result = fs.select(
            [{"a": 1, "b": 2}],
            {"strategy": "manual", "keep_fields": "not a list"},
        )
        assert result == [{"a": 1, "b": 2}]

    def test_mixed_records_filtered(self):
        fs = FeatureSelector()
        result = fs.select(
            [None, "bad", {"a": 1}],
            {"strategy": "manual", "keep_fields": ["a"]},
        )
        assert len(result) == 1


class TestFeatureSelectorImportance:
    def test_empty_features(self):
        fs = FeatureSelector()
        assert fs.calculate_feature_importance([], "sales") == {}

    def test_missing_target_field(self):
        fs = FeatureSelector()
        assert fs.calculate_feature_importance(
            [{"a": 1}], "sales"
        ) == {}

    def test_non_string_target_field(self):
        fs = FeatureSelector()
        assert fs.calculate_feature_importance(
            [{"a": 1}], None  # type: ignore[arg-type]
        ) == {}

    def test_non_dict_records_filtered(self):
        fs = FeatureSelector()
        result = fs.calculate_feature_importance(
            [None, "bad", {"x": 1, "target": 10}, {"x": 2, "target": 20}],
            "target",
        )
        assert "x" in result


# ═══════════════════════════════════════════════════════════
# FeatureStore
# ═══════════════════════════════════════════════════════════


class TestFeatureStoreDefensive:
    def test_validate_name_none(self, tmp_path):
        """Regression: pre-audit ``re.match()`` raised
        TypeError on None name."""
        fs = FeatureStore(store_dir=str(tmp_path))
        with pytest.raises(FeatureStoreError, match="non-empty string"):
            fs.store(None, [])  # type: ignore[arg-type]

    def test_validate_name_non_string(self, tmp_path):
        fs = FeatureStore(store_dir=str(tmp_path))
        with pytest.raises(FeatureStoreError):
            fs.store(42, [])  # type: ignore[arg-type]

    def test_validate_name_empty_string(self, tmp_path):
        fs = FeatureStore(store_dir=str(tmp_path))
        with pytest.raises(FeatureStoreError):
            fs.store("", [])

    def test_path_traversal_blocked(self, tmp_path):
        """``_validate_name`` regex rejects ``/`` and ``..``."""
        fs = FeatureStore(store_dir=str(tmp_path))
        with pytest.raises(FeatureStoreError):
            fs.store("../etc/passwd", [])

    def test_delete_validates_name(self, tmp_path):
        """Regression: pre-audit ``delete()`` never validated
        the name, so a caller could attempt to delete an
        arbitrary path."""
        fs = FeatureStore(store_dir=str(tmp_path))
        with pytest.raises(FeatureStoreError):
            fs.delete("../etc/passwd")

    def test_retrieve_none_name(self, tmp_path):
        fs = FeatureStore(store_dir=str(tmp_path))
        assert fs.retrieve(None) == []  # type: ignore[arg-type]

    def test_store_non_list_features_coerced(self, tmp_path):
        fs = FeatureStore(store_dir=str(tmp_path))
        fs.store("test", None)  # type: ignore[arg-type]
        assert fs.retrieve("test") == []


class TestFeatureStoreThreadSafety:
    def test_concurrent_store_retrieve(self, tmp_path):
        """Concurrent store/retrieve must not raise
        dict-size-changed errors."""
        fs = FeatureStore(store_dir=str(tmp_path))
        stop = threading.Event()
        errors: list[Exception] = []

        def writer(i: int):
            try:
                while not stop.is_set():
                    fs.store(f"set_{i % 3}", [{"v": i}])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def reader():
            try:
                while not stop.is_set():
                    fs.retrieve("set_0")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        threads.append(threading.Thread(target=reader))
        for t in threads:
            t.start()
        import time
        time.sleep(0.15)
        stop.set()
        for t in threads:
            t.join(timeout=2)
        assert not errors


# ═══════════════════════════════════════════════════════════
# Pipelines
# ═══════════════════════════════════════════════════════════


class TestAnalyticsPipeline:
    def test_none_input(self, tmp_path, monkeypatch):
        import data_pipeline.feature_engineering.feature_store as fs_mod
        monkeypatch.setattr(fs_mod, "_STORE_DIR", str(tmp_path))
        pipeline = AnalyticsPipeline()
        result = pipeline.run(None)
        assert result["stats"]["total_input"] == 0
        assert result["records"] == []

    def test_non_list_input(self, tmp_path, monkeypatch):
        import data_pipeline.feature_engineering.feature_store as fs_mod
        monkeypatch.setattr(fs_mod, "_STORE_DIR", str(tmp_path))
        pipeline = AnalyticsPipeline()
        result = pipeline.run("not a list")
        assert result["stats"]["total_input"] == 0

    def test_compute_metrics_currency_strings(self):
        """Regression: bare float() crashed on currency."""
        result = _compute_analytics_metrics({
            "sessions": "100",
            "totalRevenue": "$1,234.56",
            "bounceRate": "0.35",
            "screenPageViews": "450",
        })
        assert result["session_value"] == round(1234.56 / 100, 4)

    def test_compute_metrics_non_dict(self):
        assert _compute_analytics_metrics(None) == {}
        assert _compute_analytics_metrics("bad") == {}


class TestMarketingPipeline:
    def test_none_input(self, tmp_path, monkeypatch):
        import data_pipeline.feature_engineering.feature_store as fs_mod
        monkeypatch.setattr(fs_mod, "_STORE_DIR", str(tmp_path))
        pipeline = MarketingPipeline()
        result = pipeline.run(None)
        assert result["stats"]["total_input"] == 0

    def test_mixed_input(self, tmp_path, monkeypatch):
        import data_pipeline.feature_engineering.feature_store as fs_mod
        monkeypatch.setattr(fs_mod, "_STORE_DIR", str(tmp_path))
        pipeline = MarketingPipeline()
        result = pipeline.run([
            None,
            "bad",
            42,
            {
                "campaign_id": "c1", "platform": "fb",
                "impressions": 1000, "clicks": 50, "spend": 100.0,
                "conversions": 5,
            },
        ])
        # One dict passed validation (with correct types).
        assert result["stats"]["total_input"] == 4

    def test_compute_ad_metrics_currency(self):
        result = _compute_ad_metrics({
            "impressions": "10000",
            "clicks": "500",
            "spend": "$500.00",
            "conversions": "25",
            "revenue": "$2,500.00",
        })
        assert result["ctr"] == round(500 / 10000, 6)
        assert result["roas"] == round(2500.0 / 500.0, 4)

    def test_compute_ad_metrics_non_dict(self):
        assert _compute_ad_metrics(None) == {}


class TestProductPipeline:
    def test_none_input(self, tmp_path, monkeypatch):
        import data_pipeline.feature_engineering.feature_store as fs_mod
        monkeypatch.setattr(fs_mod, "_STORE_DIR", str(tmp_path))
        pipeline = ProductPipeline()
        result = pipeline.run(None)
        assert result["stats"]["total_input"] == 0

    def test_non_list_input(self, tmp_path, monkeypatch):
        import data_pipeline.feature_engineering.feature_store as fs_mod
        monkeypatch.setattr(fs_mod, "_STORE_DIR", str(tmp_path))
        pipeline = ProductPipeline()
        result = pipeline.run("not a list")
        assert result["stats"]["total_input"] == 0
