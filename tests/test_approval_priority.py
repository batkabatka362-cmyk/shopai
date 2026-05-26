"""Tests for engines._approval_priority."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines._approval_priority import (
    PriorityScore,
    score_action,
    score_pending,
)


def _action(*, action_id="a", engine="loyalty",
            risk_class="additive", params=None,
            confidence=None):
    return SimpleNamespace(
        id=action_id,
        engine=engine,
        risk_class=risk_class,
        params=params or {},
        confidence=confidence,
    )


class TestRecommendationBands:

    def test_urgent_when_high(self):
        # destructive (1.0) + high spend + low ROAS + regression
        action = _action(
            risk_class="destructive",
            params={"cost": 5000},
        )
        s = score_action(
            action,
            roas_lookup={"loyalty": 0.2},
            regressing_engines={"loyalty"},
        )
        assert s.recommendation == "urgent"

    def test_auto_ok_when_low(self):
        action = _action(
            risk_class="additive",
            params={},
            confidence=0.95,
        )
        s = score_action(action, roas_lookup={"loyalty": 5.0})
        assert s.recommendation == "auto-ok"

    def test_normal_in_middle(self):
        # Modification + moderate spend + low ROAS = normal
        # band (0.4 -- 0.7). Pick params so total score sits
        # comfortably in middle.
        action = _action(
            risk_class="modification",
            params={"cost": 1000},
            confidence=0.5,
        )
        s = score_action(
            action,
            roas_lookup={"loyalty": 1.5},  # break-even
        )
        # 0.6*0.30 + ~0.75*0.25 + 0.3*0.20 + 0.0 + 0.5*0.10 = ~0.47
        assert s.recommendation == "normal"


class TestComponents:

    def test_risk_dominates_destructive(self):
        action = _action(risk_class="destructive", params={})
        s = score_action(action)
        assert s.components["risk"] == 1.0

    def test_risk_additive_low(self):
        action = _action(risk_class="additive")
        s = score_action(action)
        assert s.components["risk"] == 0.2

    def test_spend_zero_when_no_params(self):
        action = _action(params={})
        s = score_action(action)
        assert s.components["spend"] == 0.0

    def test_spend_log_scaled(self):
        action_small = _action(params={"cost": 10})
        action_large = _action(params={"cost": 10000})
        s_small = score_action(action_small)
        s_large = score_action(action_large)
        # Large > small but both <= 1.0
        assert s_large.components["spend"] > s_small.components["spend"]
        assert s_large.components["spend"] <= 1.0

    def test_roas_strong_zero_priority(self):
        action = _action(engine="loyalty")
        s = score_action(action, roas_lookup={"loyalty": 5.0})
        assert s.components["roas"] == 0.0

    def test_roas_negative_high_priority(self):
        action = _action(engine="loyalty")
        s = score_action(action, roas_lookup={"loyalty": 0.3})
        assert s.components["roas"] >= 0.7

    def test_regression_engine_adds_priority(self):
        action_yes = _action(engine="loyalty")
        action_no = _action(engine="other")
        s_yes = score_action(
            action_yes, regressing_engines={"loyalty"},
        )
        s_no = score_action(
            action_no, regressing_engines={"loyalty"},
        )
        assert s_yes.components["regression"] == 1.0
        assert s_no.components["regression"] == 0.0

    def test_low_confidence_high_priority(self):
        a_low = _action(confidence=0.1)
        a_high = _action(confidence=0.95)
        s_low = score_action(a_low)
        s_high = score_action(a_high)
        assert s_low.components["confidence"] > s_high.components["confidence"]


class TestPriorityScoreReason:

    def test_reason_picks_top_two_components(self):
        action = _action(
            risk_class="destructive",
            params={"cost": 5000},
        )
        s = score_action(
            action,
            roas_lookup={"loyalty": 0.3},
        )
        # Reason should mention "risk" (top component, 1.0)
        assert "risk=" in s.reason


class TestScorePending:

    def test_empty_actions_returns_empty(self):
        result = score_pending(actions=[], use_context=False)
        assert result == []

    def test_sorted_desc_by_score(self):
        actions = [
            _action(action_id="a1", risk_class="additive"),
            _action(action_id="a2", risk_class="destructive"),
            _action(action_id="a3", risk_class="modification"),
        ]
        result = score_pending(
            actions=actions, use_context=False,
        )
        # destructive (highest risk) first
        assert result[0].action_id == "a2"
        # additive last
        assert result[-1].action_id == "a1"

    def test_context_disabled_for_test_isolation(self):
        """use_context=False skips ROAS + regression lookups,
        which would otherwise hit real substrate state."""
        actions = [_action()]
        result = score_pending(
            actions=actions, use_context=False,
        )
        assert result[0].components["roas"] == 0.0
        assert result[0].components["regression"] == 0.0
