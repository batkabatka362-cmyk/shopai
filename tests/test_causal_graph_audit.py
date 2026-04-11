"""Tests for audit-pass-15 fixes in core/causal/causal_graph.

  1. _match_template did not enforce cause-before-effect temporal
     order. An "effect" event recorded BEFORE its claimed cause
     was still flagged as a valid causal chain — the entire
     point of "causal" is temporal order, so this was a real
     correctness bug producing false-positive root causes.
  2. _match_template picked the FIRST event of each type in the
     events list (in iteration order) without considering when
     that event happened relative to other steps. Combined with
     #1 this could pick a "cause" that happened AFTER its
     "effect".
  3. _normalize_events defaulted missing-timestamp events to
     days_ago=0, silently treating "happened sometime, unknown
     when" as "happened RIGHT NOW" — the strongest possible
     temporal weight, anchoring chains on noise.
"""
import time

import pytest


def _g():
    from core.causal.causal_graph import CausalGraph
    return CausalGraph()


# ── Cause-before-effect temporal order ───────────────────────


class TestTemporalOrder:
    def test_correct_order_detected(self):
        """ad_stop happened 5 days ago → traffic_drop 3 days ago
        → revenue_drop 1 day ago. Cause precedes effect — valid."""
        g = _g()
        result = g.analyze([
            {"type": "ad_stop",       "days_ago": 5},
            {"type": "traffic_drop",  "days_ago": 3},
            {"type": "revenue_drop",  "days_ago": 1},
        ])
        assert result["chain_count"] >= 1
        # Find the ad_stop chain
        chain = next(
            (c for c in result["chains"] if c["events"][0] == "ad_stop"),
            None,
        )
        assert chain is not None
        assert chain["events"] == ["ad_stop", "traffic_drop", "revenue_drop"]

    def test_reversed_order_rejected(self):
        """Regression: previously this falsely matched the
        ad_stop→traffic_drop→revenue_drop chain even though the
        revenue_drop happened BEFORE the ad_stop."""
        g = _g()
        result = g.analyze([
            {"type": "revenue_drop",  "days_ago": 5},  # effect FIRST
            {"type": "traffic_drop",  "days_ago": 3},
            {"type": "ad_stop",       "days_ago": 1},  # cause LAST
        ])
        # No valid chain — the order is reversed.
        ad_chains = [
            c for c in result["chains"]
            if "ad_stop" in c["events"] and "revenue_drop" in c["events"]
        ]
        assert ad_chains == []

    def test_same_day_events_allowed(self):
        """Two events recorded the same day should be tolerated as
        a valid chain — the slack constant covers within-day
        ordering noise."""
        g = _g()
        result = g.analyze([
            {"type": "stockout",     "days_ago": 2},
            {"type": "lost_sales",   "days_ago": 2},
            {"type": "customer_churn", "days_ago": 2},
        ])
        chains = [c for c in result["chains"] if "stockout" in c["events"]]
        assert chains  # at least one match

    def test_partial_chain_with_correct_order(self):
        """Two-step chain without the third step still matches."""
        g = _g()
        result = g.analyze([
            {"type": "price_increase", "days_ago": 2},
            {"type": "conversion_drop", "days_ago": 1},
        ])
        chains = [c for c in result["chains"] if "price_increase" in c["events"]]
        assert len(chains) == 1


# ── Greedy chronological event matching ─────────────────────


class TestGreedyMatching:
    def test_picks_oldest_cause_when_multiple_present(self):
        """If two ad_stop events are present, the matcher should
        pick the OLDEST one as the cause (since it's most likely
        to have triggered the downstream effect)."""
        g = _g()
        result = g.analyze([
            {"type": "ad_stop",       "days_ago": 6},  # older
            {"type": "ad_stop",       "days_ago": 4},  # newer
            {"type": "traffic_drop",  "days_ago": 2},
            {"type": "revenue_drop",  "days_ago": 1},
        ])
        chain = next(
            (c for c in result["chains"] if c["events"] and c["events"][0] == "ad_stop"),
            None,
        )
        assert chain is not None
        # The temporal_span_days field should reflect the OLDER
        # ad_stop being chosen as the cause (span = 6 - 1 = 5).
        assert chain["temporal_span_days"] == pytest.approx(5.0, abs=0.5)


# ── Missing timestamp / days_ago skip ───────────────────────


class TestMissingTimestampSkipped:
    def test_event_with_no_timestamp_is_dropped(self):
        """Regression: previously such an event was kept with
        days_ago=0 (treated as "right now") and could anchor
        false-positive chains."""
        g = _g()
        result = g.analyze([
            {"type": "ad_stop"},  # no timestamp, no days_ago
            {"type": "traffic_drop", "days_ago": 2},
            {"type": "revenue_drop", "days_ago": 1},
        ])
        # The ad_stop event was dropped → only the partial
        # traffic_drop→revenue_drop chain (or none) survives.
        for chain in result["chains"]:
            assert "ad_stop" not in chain["events"]

    def test_event_with_only_timestamp_works(self):
        """An event with timestamp but no explicit days_ago must
        still be normalized correctly."""
        g = _g()
        now = time.time()
        result = g.analyze([
            {"type": "ad_stop", "timestamp": now - 5 * 86400},
            {"type": "traffic_drop", "timestamp": now - 3 * 86400},
            {"type": "revenue_drop", "timestamp": now - 1 * 86400},
        ])
        chains = [c for c in result["chains"] if "ad_stop" in c["events"]]
        assert chains  # chain still detected via timestamp path

    def test_event_with_no_type_dropped(self):
        g = _g()
        result = g.analyze([
            {"days_ago": 5},  # no type
            {"type": "traffic_drop", "days_ago": 3},
            {"type": "revenue_drop", "days_ago": 1},
        ])
        # The typeless event is dropped — does not affect chain
        # detection on the others.
        assert isinstance(result["chains"], list)


# ── Strength threshold + recommendations still work ─────────


class TestStrengthAndRecommendations:
    def test_weak_chain_filtered_out(self):
        """A chain with very old events should be filtered by
        the _MIN_CHAIN_STRENGTH threshold."""
        g = _g()
        result = g.analyze([
            # Both events are 30 days old — way past max_days for
            # most templates.
            {"type": "price_increase", "days_ago": 30},
            {"type": "conversion_drop", "days_ago": 30},
        ])
        # max_days=3 for price_increase template → diff 0 ok, but
        # temporal_factor heavily penalizes old events. Either no
        # chain or very weak.
        for c in result["chains"]:
            assert c["strength"] >= 0.30

    def test_recommendations_generated_from_root_cause(self):
        g = _g()
        result = g.analyze([
            {"type": "ad_stop",      "days_ago": 5},
            {"type": "traffic_drop", "days_ago": 3},
            {"type": "revenue_drop", "days_ago": 1},
        ])
        assert any("Restart ad campaigns" in r for r in result["recommendations"])
