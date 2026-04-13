"""Tests for audit-pass-14 fixes in core/learning/root_cause_analyzer.

  1. _get_successes / _counterfactual / analyze_pattern called
     into the episodic memory backend without try/except. Any
     backend exception (DB locked, missing method, schema drift)
     propagated up and crashed the whole root-cause analysis,
     even though the rest of the analyzer can fall back
     gracefully on partial data.
  2. _factor_attribution used a unit-blind absolute threshold of
     `abs(diff) > 0.5` to flag a "meaningful difference". That
     correctly fired on grade-style 1-5 scales but completely
     missed sub-1 fractional scales: churn_pct=0.05 vs 0.30 is
     a 6x difference but `abs(0.25) < 0.5` so the analyzer
     silently dropped one of the most important factors.
"""
import pytest


def _analyzer(memory=None):
    from core.learning.root_cause_analyzer import RootCauseAnalyzer
    return RootCauseAnalyzer(episodic_memory=memory)


# ── Memory exception isolation ───────────────────────────────


class TestMemoryExceptionIsolation:
    def test_get_successes_swallows_recall_exception(self, monkeypatch):
        from core.learning import root_cause_analyzer as rca_mod

        class _BrokenMem:
            def recall_similar(self, *a, **k):
                raise RuntimeError("memory dead")

        warnings: list[str] = []
        monkeypatch.setattr(
            rca_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        analyzer = _analyzer(_BrokenMem())
        # Driving _get_successes via analyze_failure end-to-end
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"health_grade": "D", "churn_pct": 0.20},
            "action": "raise",
        })
        # Did not crash. Did log a warning. Returned a usable dict.
        assert "root_causes" in result
        assert any("recall_similar" in w and "memory dead" in w for w in warnings)

    def test_counterfactual_swallows_recall_exception(self, monkeypatch):
        from core.learning import root_cause_analyzer as rca_mod

        # Memory whose recall_similar succeeds the first time
        # (used by _get_successes) but raises the second time
        # (used by _counterfactual).
        call = {"n": 0}

        class _MemFlaky:
            def recall_similar(self, *a, **k):
                call["n"] += 1
                if call["n"] == 1:
                    return []
                raise RuntimeError("counterfactual dead")

        warnings: list[str] = []
        monkeypatch.setattr(
            rca_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        analyzer = _analyzer(_MemFlaky())
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"health_grade": "F"},
            "action": "raise",
        })
        # The counterfactual block records the failure but
        # analyze_failure still returns successfully.
        assert result["counterfactual"]["available"] is False
        assert "error" in result["counterfactual"]
        assert any("counterfactual" in w for w in warnings)

    def test_analyze_pattern_swallows_get_failures_exception(self, monkeypatch):
        from core.learning import root_cause_analyzer as rca_mod

        class _BrokenMem:
            def get_failures(self, **k):
                raise RuntimeError("get_failures dead")

        warnings: list[str] = []
        monkeypatch.setattr(
            rca_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        analyzer = _analyzer(_BrokenMem())
        result = analyzer.analyze_pattern("pricing")
        assert result["status"] == "memory_error"
        assert "get_failures dead" in result["error"]
        assert any("get_failures" in w for w in warnings)

    def test_no_memory_path_unchanged(self):
        analyzer = _analyzer(None)
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"health_grade": "D"},
            "action": "raise",
        })
        assert "root_causes" in result
        # No comparison data with no memory wired
        ctx = result["contributing_factors"]
        assert any("no_comparison_data" in str(c) for c in ctx)


# ── Factor attribution relative threshold ───────────────────


class TestFactorAttributionRelativeThreshold:
    def _mem_with_successes(self, success_ctx):
        class _Mem:
            def recall_similar(self, ctx, limit=50):
                return [{
                    "success": True,
                    "decision_type": "pricing",
                    "context": success_ctx,
                }]
        return _Mem()

    def test_small_fractional_diff_now_detected(self):
        """Regression: previously a 6x churn diff (0.05 vs 0.30)
        was silently dropped because abs(0.25) < 0.5. Now the
        relative-diff branch catches it."""
        analyzer = _analyzer(self._mem_with_successes(
            {"churn_pct": 0.05, "health_grade": "B"},
        ))
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"churn_pct": 0.30, "health_grade": "B"},
            "action": "raise",
        })
        # The churn factor should now appear in contributing factors.
        factors = [f["factor"] for f in result["contributing_factors"]]
        assert "churn_pct" in factors

    def test_large_absolute_diff_still_detected(self):
        """The fix must not regress the large-value path."""
        analyzer = _analyzer(self._mem_with_successes(
            {"confidence_score": 90},
        ))
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"confidence_score": 30},
            "action": "raise",
        })
        factors = [f["factor"] for f in result["contributing_factors"]]
        assert "confidence_score" in factors

    def test_grade_diff_still_detected(self):
        analyzer = _analyzer(self._mem_with_successes(
            {"health_grade": "A"},
        ))
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"health_grade": "D"},
            "action": "raise",
        })
        factors = [f["factor"] for f in result["contributing_factors"]]
        assert "health_grade" in factors

    def test_tiny_diff_not_flagged(self):
        analyzer = _analyzer(self._mem_with_successes(
            {"churn_pct": 0.10},
        ))
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"churn_pct": 0.105},
            "action": "raise",
        })
        # 0.105 vs 0.10 = 5% relative diff, well below 50% threshold.
        factors = [f["factor"] for f in result["contributing_factors"]]
        assert "churn_pct" not in factors

    def test_relative_difference_field_populated(self):
        analyzer = _analyzer(self._mem_with_successes(
            {"churn_pct": 0.05},
        ))
        result = analyzer.analyze_failure({
            "decision_type": "pricing",
            "context": {"churn_pct": 0.30},
            "action": "raise",
        })
        churn = next(
            f for f in result["contributing_factors"]
            if f.get("factor") == "churn_pct"
        )
        assert "relative_difference" in churn
        # 0.30 vs 0.05: max=0.30, diff=0.25, relative ≈ 0.833
        assert 0.8 <= churn["relative_difference"] <= 0.85
