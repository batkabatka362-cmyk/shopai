"""Test suite for the 12-layer system — import, config, execution.

Verifies that all layers can be imported, instantiated, have a run() method,
and that config files list their engines. Also runs DataLayerFlow and
FinancialLayerFlow with minimal input and checks graceful error handling.
"""
import unittest


# All 12 layer classes from layers/__init__.py
LAYER_CLASSES = [
    ("layers.data_layer", "DataLayerFlow"),
    ("layers.analysis_layer", "AnalysisLayerFlow"),
    ("layers.product_layer", "ProductLayerFlow"),
    ("layers.pricing_layer", "PricingLayerFlow"),
    ("layers.customer_layer", "CustomerLayerFlow"),
    ("layers.marketing_layer", "MarketingLayerFlow"),
    ("layers.sales_layer", "SalesLayerFlow"),
    ("layers.operations_layer", "OperationsLayerFlow"),
    ("layers.financial_layer", "FinancialLayerFlow"),
    ("layers.intelligence_layer", "IntelligenceLayerFlow"),
    ("layers.execution_layer", "ExecutionLayerFlow"),
    ("layers.scaling_layer", "ScalingLayerFlow"),
]

# Config module path and expected config variable name for each layer
LAYER_CONFIGS = [
    ("layers.data_layer.config", "DATA_LAYER_CONFIG"),
    ("layers.analysis_layer.config", "ANALYSIS_LAYER_CONFIG"),
    ("layers.product_layer.config", "PRODUCT_LAYER_CONFIG"),
    ("layers.pricing_layer.config", "PRICING_LAYER_CONFIG"),
    ("layers.customer_layer.config", "CUSTOMER_LAYER_CONFIG"),
    ("layers.marketing_layer.config", "MARKETING_LAYER_CONFIG"),
    ("layers.sales_layer.config", "SALES_LAYER_CONFIG"),
    ("layers.operations_layer.config", "OPERATIONS_LAYER_CONFIG"),
    ("layers.financial_layer.config", "FINANCIAL_LAYER_CONFIG"),
    ("layers.intelligence_layer.config", "INTELLIGENCE_LAYER_CONFIG"),
    ("layers.execution_layer.config", "EXECUTION_LAYER_CONFIG"),
    ("layers.scaling_layer.config", "SCALING_LAYER_CONFIG"),
]


def _payload(data: dict) -> dict:
    """Build a standard layer/engine input payload."""
    return {"status": "success", "data": data, "meta": {}, "error": None}


def _error_payload(reason: str = "upstream broke") -> dict:
    return {"status": "error", "data": {}, "meta": {}, "error": reason}


# ======================================================================
# Layer Import Tests
# ======================================================================


class TestLayerImport(unittest.TestCase):
    """Verify all 12 layers can be imported and have the expected interface."""

    def test_all_layers_import(self):
        """All 12 layers should import without error."""
        import importlib
        errors = []
        for module_path, class_name in LAYER_CLASSES:
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name, None)
                self.assertIsNotNone(
                    cls,
                    f"{class_name} not found in {module_path}",
                )
            except Exception as exc:
                errors.append(f"{module_path}.{class_name}: {exc}")
        self.assertEqual(errors, [], f"Import failures: {errors}")

    def test_all_layers_have_run(self):
        """Every layer flow class must have a callable run() method."""
        import importlib
        for module_path, class_name in LAYER_CLASSES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(
                hasattr(instance, "run"),
                f"{class_name} missing run()",
            )
            self.assertTrue(
                callable(instance.run),
                f"{class_name}.run not callable",
            )

    def test_all_layers_have_layer_name(self):
        """Every layer flow class should have a LAYER_NAME attribute."""
        import importlib
        for module_path, class_name in LAYER_CLASSES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(
                hasattr(instance, "LAYER_NAME"),
                f"{class_name} missing LAYER_NAME",
            )
            self.assertIsInstance(instance.LAYER_NAME, str)
            self.assertGreater(len(instance.LAYER_NAME), 0)

    def test_layer_config_exists(self):
        """Each layer should have a config module with an engines list."""
        import importlib
        errors = []
        for config_path, config_var in LAYER_CONFIGS:
            try:
                mod = importlib.import_module(config_path)
                config = getattr(mod, config_var, None)
                self.assertIsNotNone(
                    config,
                    f"{config_var} not found in {config_path}",
                )
                self.assertIsInstance(config, dict, f"{config_var} is not a dict")
                self.assertIn(
                    "engines", config,
                    f"{config_var} missing 'engines' key",
                )
                self.assertIsInstance(
                    config["engines"], list,
                    f"{config_var}['engines'] is not a list",
                )
                self.assertGreater(
                    len(config["engines"]), 0,
                    f"{config_var}['engines'] is empty",
                )
            except Exception as exc:
                errors.append(f"{config_path}: {exc}")
        self.assertEqual(errors, [], f"Config failures: {errors}")

    def test_layer_configs_have_required_engines(self):
        """Each config should declare required_engines as a list."""
        import importlib
        for config_path, config_var in LAYER_CONFIGS:
            mod = importlib.import_module(config_path)
            config = getattr(mod, config_var)
            self.assertIn(
                "required_engines", config,
                f"{config_var} missing 'required_engines'",
            )
            self.assertIsInstance(
                config["required_engines"], list,
                f"{config_var}['required_engines'] is not a list",
            )

    def test_all_12_layers_present(self):
        """We should have exactly 12 layer classes."""
        self.assertEqual(len(LAYER_CLASSES), 12)

    def test_bulk_import_via_init(self):
        """The layers __init__ should export all 12 flow classes."""
        import layers
        for _, class_name in LAYER_CLASSES:
            self.assertTrue(
                hasattr(layers, class_name),
                f"layers.__init__ missing {class_name}",
            )


# ======================================================================
# Layer Execution Tests
# ======================================================================


class TestLayerExecution(unittest.TestCase):
    """Run layers with minimal input and verify they return valid output."""

    def test_data_layer_runs(self):
        """DataLayerFlow should run and return a valid output structure."""
        from layers.data_layer import DataLayerFlow
        layer = DataLayerFlow()
        result = layer.run(_payload({
            "source": "test",
            "shop_id": "shop_001",
        }))
        # The layer may succeed or report warnings (optional engines may fail),
        # but the structure should be valid.
        self.assertIn("status", result)
        self.assertIn("meta", result)
        if result["status"] == "success":
            self.assertIn("data", result)
            self.assertIsInstance(result["data"], dict)
            meta = result["meta"]
            self.assertIn("layer", meta)
            self.assertEqual(meta["layer"], "data_layer")
            self.assertIn("engines_ran", meta)
            self.assertIn("elapsed_seconds", meta)

    def test_financial_layer_runs(self):
        """FinancialLayerFlow should run and return a valid output structure."""
        from layers.financial_layer import FinancialLayerFlow
        layer = FinancialLayerFlow()
        result = layer.run(_payload({
            "orders": [
                {"id": "o1", "total": 100, "date": "2026-04-01", "cost": 60},
                {"id": "o2", "total": 250, "date": "2026-04-02", "cost": 150},
            ],
            "products": [
                {"id": "p1", "title": "Widget", "price": 29.99, "cost": 15.00},
            ],
            "customers": [{"id": "c1"}],
            "costs": {"shipping": 5.0, "marketing": 20.0},
            "period": {"start": "2026-04-01", "end": "2026-04-30"},
        }))
        self.assertIn("status", result)
        self.assertIn("meta", result)
        if result["status"] == "success":
            self.assertEqual(result["meta"]["layer"], "financial_layer")
            self.assertIn("engines_ran", result["meta"])

    def test_layer_handles_upstream_error(self):
        """Layers should propagate upstream error status."""
        from layers.data_layer import DataLayerFlow
        layer = DataLayerFlow()
        result = layer.run(_error_payload("database unreachable"))
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])

    def test_layer_handles_missing_engines(self):
        """Layers should gracefully handle engines that return error.

        Optional engines that fail should produce warnings, not crash the layer.
        """
        from layers.data_layer import DataLayerFlow
        layer = DataLayerFlow()
        # Provide minimal data — some optional engines may error out
        result = layer.run(_payload({}))
        self.assertIn("status", result)
        # Either success with warnings or error from required engine
        if result["status"] == "error":
            self.assertIsNotNone(result["error"])
        else:
            self.assertIn("warnings", result["meta"])

    def test_layer_output_has_error_field(self):
        """Both success and error outputs should include an error field."""
        from layers.financial_layer import FinancialLayerFlow
        layer = FinancialLayerFlow()
        result = layer.run(_payload({"orders": [], "products": []}))
        self.assertIn("error", result)

    def test_layer_meta_has_timestamp(self):
        """Layer output meta should include a timestamp."""
        from layers.data_layer import DataLayerFlow
        layer = DataLayerFlow()
        result = layer.run(_payload({"source": "test"}))
        self.assertIn("meta", result)
        self.assertIn("timestamp", result["meta"])

    def test_layer_rejects_non_dict_input(self):
        """Passing a non-dict should return error, not crash."""
        from layers.data_layer import DataLayerFlow
        layer = DataLayerFlow()
        result = layer.run("not a dict")  # type: ignore[arg-type]
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
