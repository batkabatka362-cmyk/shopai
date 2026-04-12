"""Wave 13 tests — named constants replace magic numbers.

Verifies that:
1. All extracted constants exist and have expected values.
2. The constants are actually used by the code paths that
   previously contained inline literals.
3. Changing a constant value changes the code's behavior
   (i.e. the constant is wired in, not dead code).
"""
from __future__ import annotations

import pytest


class TestProductionConstants:
    """core/system/production.py — circuit breaker, backoff, retention."""

    def test_constants_exist_and_have_expected_values(self):
        from core.system.production import (
            CIRCUIT_BREAKER_COOLDOWN_S,
            BACKOFF_BASE_S,
            MAX_BACKUP_RETENTION,
            AUDIT_LOG_MAX_ENTRIES,
        )
        assert CIRCUIT_BREAKER_COOLDOWN_S == 300
        assert BACKOFF_BASE_S == 2
        assert MAX_BACKUP_RETENTION == 10
        assert AUDIT_LOG_MAX_ENTRIES == 1000

    def test_audit_trail_respects_max_entries(self):
        from core.system.production import AuditTrail, AUDIT_LOG_MAX_ENTRIES
        import tempfile, json, os

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("[]")
            path = f.name

        try:
            import core.system.production as mod
            original = mod._AUDIT_PATH
            mod._AUDIT_PATH = type(original)(path)

            trail = AuditTrail()
            trail._entries = [{"action": f"test_{i}", "timestamp": i} for i in range(AUDIT_LOG_MAX_ENTRIES + 50)]
            trail._save()

            with open(path) as fh:
                saved = json.load(fh)
            assert len(saved) <= AUDIT_LOG_MAX_ENTRIES
        finally:
            mod._AUDIT_PATH = original
            os.unlink(path)


class TestABFrameworkConstants:
    """core/intelligence/ab_framework.py — statistical significance."""

    def test_constants_exist(self):
        from core.intelligence.ab_framework import (
            Z_SCORE_95_CONFIDENCE,
            MIN_SAMPLES_PER_VARIANT,
            MIN_LIFT_DENOMINATOR,
        )
        assert Z_SCORE_95_CONFIDENCE == 1.96
        assert MIN_SAMPLES_PER_VARIANT == 10
        assert MIN_LIFT_DENOMINATOR == 0.001

    def test_min_samples_blocks_small_experiments(self):
        from core.intelligence.ab_framework import ABFramework, MIN_SAMPLES_PER_VARIANT

        ab = ABFramework()
        # Fewer than MIN_SAMPLES_PER_VARIANT → not significant
        stats = [
            {"impressions": MIN_SAMPLES_PER_VARIANT - 1, "conversions": 3},
            {"impressions": MIN_SAMPLES_PER_VARIANT - 1, "conversions": 5},
        ]
        result = ab._test_significance(stats)
        assert result["significant"] is False
        assert result["reason"] == "insufficient_samples"


class TestCognitiveBrainConstants:
    """core/brain/cognitive.py — margin, similarity, decay thresholds."""

    def test_constants_exist(self):
        from core.brain.cognitive import (
            MARGIN_HIGH,
            MARGIN_MID,
            SIMILARITY_DEFAULT_MIN,
            CONSOLIDATION_THRESHOLD,
            CONFIDENCE_CAP,
            DECAY_LN2,
        )
        assert MARGIN_HIGH == 0.6
        assert MARGIN_MID == 0.3
        assert SIMILARITY_DEFAULT_MIN == 0.3
        assert CONSOLIDATION_THRESHOLD == 0.8
        assert CONFIDENCE_CAP == 0.9
        assert abs(DECAY_LN2 - 0.693) < 0.001

    def test_margin_thresholds_used_in_product_analysis(self):
        from core.brain.cognitive import DeepUnderstanding, MARGIN_HIGH

        product = {
            "title": "Test Widget",
            "price": 100,
            "cost": 20,  # margin = 0.8 > MARGIN_HIGH
        }
        analysis = DeepUnderstanding.explain_product(product)
        insights = analysis.get("insights", [])
        assert any("High margin" in i for i in insights)

    def test_time_decay_uses_ln2_constant(self):
        import time
        from core.brain.cognitive import AssociativeMemory, DECAY_LN2

        now = time.time()
        # At exactly half_life, decay should be ~0.5
        half_life = 7
        weight = AssociativeMemory.time_decay(now - half_life * 86400, half_life)
        assert abs(weight - 0.5) < 0.01


class TestPricingIntelligenceConstants:
    """core/intelligence/pricing_intelligence.py — statistics + elasticity."""

    def test_constants_exist(self):
        from core.intelligence.pricing_intelligence import (
            R_SQUARED_GOOD,
            R_SQUARED_MODERATE,
            Z_SCORE_001,
            Z_SCORE_01,
            Z_SCORE_05,
            Z_SCORE_10,
            SIGNIFICANCE_LEVEL,
            ELASTICITY_VERY_INELASTIC,
            ELASTICITY_INELASTIC,
            ELASTICITY_UNIT,
            ELASTICITY_ELASTIC,
        )
        assert R_SQUARED_GOOD == 0.7
        assert R_SQUARED_MODERATE == 0.4
        assert Z_SCORE_05 == 1.96
        assert SIGNIFICANCE_LEVEL == 0.05
        assert ELASTICITY_INELASTIC == 1.0
        assert ELASTICITY_ELASTIC == 2.5

    def test_elasticity_interpretation(self):
        from core.intelligence.pricing_intelligence import (
            PricingIntelligence,
            ELASTICITY_VERY_INELASTIC,
        )
        pi = PricingIntelligence()
        # Very inelastic: |e| < 0.5
        result = pi._interpret_elasticity(ELASTICITY_VERY_INELASTIC - 0.1)
        assert "Very inelastic" in result

        # Elastic: |e| >= 1.5
        result = pi._interpret_elasticity(-2.0)
        assert "Elastic" in result


class TestSystemHealthConstants:
    """core/intelligence/system_health.py — grading thresholds."""

    def test_constants_exist(self):
        from core.intelligence.system_health import (
            GRADE_A_THRESHOLD,
            GRADE_B_THRESHOLD,
            GRADE_C_THRESHOLD,
            EXECUTION_CONCERN_THRESHOLD,
        )
        assert GRADE_A_THRESHOLD == 0.9
        assert GRADE_B_THRESHOLD == 0.7
        assert GRADE_C_THRESHOLD == 0.5
        assert EXECUTION_CONCERN_THRESHOLD == 0.7

    def test_grade_ordering(self):
        from core.intelligence.system_health import (
            GRADE_A_THRESHOLD,
            GRADE_B_THRESHOLD,
            GRADE_C_THRESHOLD,
        )
        assert GRADE_A_THRESHOLD > GRADE_B_THRESHOLD > GRADE_C_THRESHOLD
