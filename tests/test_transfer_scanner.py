"""Tests for engines._transfer_scanner."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from engines._transfer_scanner import (
    TransferCandidate,
    TransferScanReport,
    _score_candidate,
    scan_empire_transfers,
)


def _action(*, action_id="a", store_id="A", engine="loyalty",
            action_type="apply", capability="SHOPIFY_X"):
    return SimpleNamespace(
        id=action_id,
        store_id=store_id,
        engine=engine,
        action_type=action_type,
        capability=capability,
    )


def _outcome(*, polarity="positive", revenue=0.0):
    return {
        "polarity": polarity,
        "metrics": {"revenue": revenue},
    }


def _fake_queue(*, executed, outcomes_map):
    q = MagicMock()
    q.list_by_status.return_value = executed
    q.get_outcomes.side_effect = lambda aid: (
        outcomes_map.get(aid, [])
    )
    return q


class TestScoreCandidate:

    def test_zero_below_min_positive(self):
        assert _score_candidate(1, 100.0) == 0.0

    def test_scales_with_positive_count(self):
        s1 = _score_candidate(2, 100.0)
        s2 = _score_candidate(10, 100.0)
        assert s2 > s1

    def test_log_scaled_revenue(self):
        s_small = _score_candidate(2, 10)
        s_large = _score_candidate(2, 10000)
        # Both positive, large > small but not 1000x
        assert s_large > s_small
        assert s_large < s_small * 4


class TestScanEmpire:

    def test_empty_when_single_store(self):
        q = _fake_queue(executed=[], outcomes_map={})
        report = scan_empire_transfers(
            queue=q, stores=["A"],
        )
        assert report.total_candidates == 0

    def test_empty_when_no_executed_actions(self):
        q = _fake_queue(executed=[], outcomes_map={})
        report = scan_empire_transfers(
            queue=q, stores=["A", "B"],
        )
        assert report.pairs_scanned == 2  # A->B + B->A
        assert report.total_candidates == 0

    def test_winner_on_a_not_tried_on_b_surfaces(self):
        # Store A: loyalty/apply ran 3 times, all positive
        actions = [
            _action(action_id="a1", store_id="A"),
            _action(action_id="a2", store_id="A"),
            _action(action_id="a3", store_id="A"),
        ]
        outcomes_map = {
            "a1": [_outcome(revenue=100)],
            "a2": [_outcome(revenue=200)],
            "a3": [_outcome(revenue=300)],
        }
        q = _fake_queue(
            executed=actions, outcomes_map=outcomes_map,
        )
        report = scan_empire_transfers(
            queue=q, stores=["A", "B"],
        )
        # A->B candidate (winner on A, untried on B)
        assert report.total_candidates >= 1
        top = report.candidates[0]
        assert top.from_store == "A"
        assert top.to_store == "B"
        assert top.engine == "loyalty"
        assert top.positive_outcomes == 3

    def test_winner_on_a_already_tried_on_b_excluded(self):
        # A: 3 successful loyalty actions. B: also tried loyalty
        # -> NOT a transfer candidate.
        actions = [
            _action(action_id="a1", store_id="A"),
            _action(action_id="a2", store_id="A"),
            _action(action_id="b1", store_id="B"),
        ]
        outcomes_map = {
            "a1": [_outcome(revenue=100)],
            "a2": [_outcome(revenue=200)],
            "b1": [],  # tried but no outcomes recorded
        }
        q = _fake_queue(
            executed=actions, outcomes_map=outcomes_map,
        )
        report = scan_empire_transfers(
            queue=q, stores=["A", "B"],
        )
        # B already tried loyalty -> not a candidate
        assert report.total_candidates == 0

    def test_below_min_positive_not_a_winner(self):
        # A: 1 positive outcome. Below min=2 default.
        actions = [
            _action(action_id="a1", store_id="A"),
        ]
        outcomes_map = {
            "a1": [_outcome(revenue=100)],
        }
        q = _fake_queue(
            executed=actions, outcomes_map=outcomes_map,
        )
        report = scan_empire_transfers(
            queue=q, stores=["A", "B"],
        )
        assert report.total_candidates == 0

    def test_top_k_limits_results(self):
        # 5 different engines all winners on A
        actions = []
        outcomes_map = {}
        for i, engine in enumerate(["e1", "e2", "e3", "e4", "e5"]):
            for j in range(3):
                aid = f"{engine}_{j}"
                actions.append(_action(
                    action_id=aid, store_id="A",
                    engine=engine,
                ))
                outcomes_map[aid] = [
                    _outcome(revenue=100 * (i + 1)),
                ]
        q = _fake_queue(
            executed=actions, outcomes_map=outcomes_map,
        )
        # 5 winners x 1 target = 5 candidates; limit to top 3
        report = scan_empire_transfers(
            queue=q, stores=["A", "B"], top_k=3,
        )
        assert report.total_candidates == 3

    def test_top_pair_returns_highest_score_pair(self):
        actions = [
            _action(action_id="a1", store_id="A"),
            _action(action_id="a2", store_id="A"),
        ]
        outcomes_map = {
            "a1": [_outcome(revenue=5000)],
            "a2": [_outcome(revenue=10000)],
        }
        q = _fake_queue(
            executed=actions, outcomes_map=outcomes_map,
        )
        report = scan_empire_transfers(
            queue=q, stores=["A", "B"],
        )
        pair = report.top_pair
        assert pair == ("A", "B")
