"""Tests for audit-pass-13 fixes in core/judgment.

  1. JudgmentAdvisor.evaluate() ran each of the 6 checks without
     try/except. A buggy downstream module (FailurePrevention,
     ActionCoordinator) raising mid-check would crash the entire
     judgment vote — the orchestrator's pre-execution gate would
     fail open by exception rather than fail closed by veto.
  2. The veto-reason extraction used `next(c["reason"] for c ...)`
     so a vetoing check that forgot to set "reason" would crash
     the whole evaluation with KeyError.
  3. _check_competitor_activity treated `situation["events"]` as
     a list without type-checking — a None or non-list value
     crashed the comprehension with TypeError.
  4. FailureContextPrevention._match_score hard-coded a floor of
     1 in `max(abs(c_val), abs(f_val), 1)`, which silently
     inflated the similarity of small fractional values.
     churn_pct=0.05 vs 0.10 came out at 95% similar even though
     they differ by 2x.
  5. _match_score also blended bool with numeric (since bool is
     a subclass of int in Python), so True/0 silently fell into
     the numeric branch.
"""
import pytest


# ── Per-check isolation ──────────────────────────────────────


class TestJudgmentPerCheckIsolation:
    def _broken_advisor(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor

        class _BrokenFailurePrev:
            def check(self, *a, **k):
                raise RuntimeError("failure_prev exploded")

        class _BrokenCoordinator:
            def check(self, *a, **k):
                raise RuntimeError("coordinator exploded")

        return JudgmentAdvisor(
            episodic_memory=None,
            failure_prevention=_BrokenFailurePrev(),
            action_coordinator=_BrokenCoordinator(),
        )

    def test_broken_check_does_not_crash_evaluate(self):
        """Regression: a broken FailurePrevention.check must
        not crash evaluate() — it falls back to a stub check.

        Fix O changed the fail-safe semantics: a broken
        check now returns risk=1.0 (max uncertainty) and is
        tagged ``degraded=True``, instead of silently
        defaulting to risk=0.0 (approval). A safety gate
        that can't assess risk must treat that as high risk.
        """
        advisor = self._broken_advisor()
        result = advisor.evaluate(
            decision={"action": "raise prices", "confidence_score": 70},
            situation={},
        )
        assert "verdict" in result
        # Broken checks are now marked degraded with risk=1.0
        broken = [c for c in result["checks"] if c.get("error")]
        assert len(broken) >= 2  # past_failures + cooldown both broken
        for c in broken:
            assert c["risk"] == 1.0
            assert c.get("degraded") is True
            assert "check failed" in c["reason"]

    def test_broken_check_logs_warning(self, monkeypatch):
        from core.judgment import judgment_advisor as ja_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            ja_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        advisor = self._broken_advisor()
        advisor.evaluate(
            decision={"action": "x", "confidence_score": 80},
            situation={},
        )
        assert any("past_failures" in w and "exploded" in w for w in warnings)
        assert any("cooldown" in w and "exploded" in w for w in warnings)

    def test_check_returning_non_dict_treated_as_degraded(self):
        """A check that returns a non-dict raises a TypeError
        inside _safe_check. Fix O: the stub lands with
        risk=1.0 + degraded=True so the invalid signal
        doesn't silently approve the decision."""
        from core.judgment.judgment_advisor import JudgmentAdvisor

        advisor = JudgmentAdvisor()
        advisor._check_magnitude = lambda decision: "not a dict"
        result = advisor.evaluate(
            decision={"action": "x", "confidence_score": 80},
            situation={},
        )
        mag = next(c for c in result["checks"] if c["check"] == "magnitude")
        assert mag["risk"] == 1.0
        assert mag.get("degraded") is True
        assert "check failed" in mag["reason"]


# ── Veto-reason defensive .get ───────────────────────────────


class TestVetoReasonDefensive:
    def test_veto_without_reason_does_not_crash(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor

        advisor = JudgmentAdvisor()
        # Inject a check that vetoes but forgot to set "reason"
        advisor._check_magnitude = lambda decision: {
            "check": "magnitude",
            "risk": 1.0,
            "weight": 0.20,
            "veto": True,
            # NOTE: deliberately no "reason" key
        }
        result = advisor.evaluate(
            decision={"action": "x", "confidence_score": 80},
            situation={},
        )
        # The defensive _safe_check fills in a default reason
        # before evaluate() reads it, and the veto extraction has
        # a fallback for the missing-reason case too.
        assert result["verdict"] == "escalate_to_human"
        assert result["reason"]  # never empty


# ── Defensive events list type ──────────────────────────────


class TestEventsTypeDefensive:
    def test_none_events_does_not_crash(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        result = advisor.evaluate(
            decision={"action": "raise prices", "confidence_score": 80},
            situation={"events": None},
        )
        assert "verdict" in result

    def test_string_events_does_not_crash(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        result = advisor.evaluate(
            decision={"action": "x", "confidence_score": 80},
            situation={"events": "malformed"},
        )
        assert "verdict" in result


# ── _match_score fractional values ──────────────────────────


class TestMatchScoreFractional:
    def _prev(self):
        from core.judgment.failure_prevention import FailureContextPrevention
        return FailureContextPrevention()

    def test_small_fractional_values_compared_relatively(self):
        """Regression: previously max(abs(c), abs(f), 1) produced
        a 95% similarity for 0.05 vs 0.10 because the floor of 1
        swamped the relative diff. Now they correctly compare as
        50% similar (2x difference)."""
        prev = self._prev()
        score = prev._match_score(
            {"churn_pct": 0.05, "net_margin": 0.05},
            {"churn_pct": 0.10, "net_margin": 0.10},
        )
        # Both factors are 50% similar → weighted average is also
        # 50%. Old buggy code would have produced ~0.95 here.
        assert 0.45 <= score <= 0.55

    def test_identical_fractional_values_match_perfectly(self):
        prev = self._prev()
        score = prev._match_score(
            {"churn_pct": 0.05},
            {"churn_pct": 0.05},
        )
        assert score == 1.0

    def test_zero_values_match_perfectly(self):
        prev = self._prev()
        score = prev._match_score(
            {"churn_pct": 0, "net_margin": 0},
            {"churn_pct": 0, "net_margin": 0},
        )
        assert score == 1.0

    def test_large_values_still_compared_relatively(self):
        """The fix must not regress the previously-correct
        behaviour for large values."""
        prev = self._prev()
        score = prev._match_score(
            {"confidence_score": 50},
            {"confidence_score": 100},
        )
        # 50 vs 100 → relative diff 0.5 → similarity 0.5
        assert 0.45 <= score <= 0.55

    def test_bool_int_no_longer_blended(self):
        """Regression: bool is a subclass of int in Python, so
        without an explicit type-mismatch guard the numeric branch
        would compare True (1) against 0 as 'similar'. Now we
        skip mismatched types entirely."""
        prev = self._prev()
        # Compare bool stockout_risk against int — should skip
        # this factor entirely so it doesn't pollute the score.
        score = prev._match_score(
            {"stockout_risk": True, "confidence_score": 50},
            {"stockout_risk": 0, "confidence_score": 50},
        )
        # Only confidence_score contributed (perfect match) →
        # score is 1.0. If the bool/int blend leaked through, we'd
        # see a lower score (or worse, a crash).
        assert score == 1.0
