"""Tests for core.adapters.triplewhale.moby (Wave C-1)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.adapters.triplewhale.moby import (
    MobyAdapter,
    MobyRecommendation,
    RLDisagreementLog,
)


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


def _build(tmp, *, http=None, api_key="tw_test"):
    return MobyAdapter(
        api_key=api_key,
        http=http or MagicMock(),
        db_path=Path(tmp) / "moby.db",
        now_fn=lambda: 1_700_000_000.0,
    )


class TestConfig(unittest.TestCase):
    def test_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, api_key="")
            self.assertFalse(a.is_available())
            a.close()

    def test_env_pickup(self):
        os.environ["TRIPLE_WHALE_API_KEY"] = "env_key"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                a = MobyAdapter(
                    db_path=Path(tmp) / "m.db",
                    http=MagicMock(),
                )
                self.assertTrue(a.is_available())
                a.close()
        finally:
            os.environ.pop(
                "TRIPLE_WHALE_API_KEY", None,
            )


class TestRecommendations(unittest.TestCase):
    def test_unconfigured_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, api_key="")
            self.assertEqual(a.recommendations(), [])
            self.assertIn(
                "not configured",
                a.stats()["last_error"],
            )
            a.close()

    def test_happy_path(self):
        http = MagicMock()
        http.get.return_value = _resp(
            200,
            payload={
                "data": [
                    {
                        "entity_id": "c1",
                        "recommendation": "increase_budget",
                        "confidence": 0.82,
                        "roas_delta": 0.35,
                    },
                    {
                        "id": "c2",
                        "action": "pause",
                        "confidence": 0.66,
                    },
                ],
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, http=http)
            recs = a.recommendations(scope="campaigns")
            self.assertEqual(len(recs), 2)
            self.assertEqual(
                recs[0].recommendation,
                "increase_budget",
            )
            self.assertEqual(
                recs[1].entity_id, "c2",
            )
            a.close()

    def test_bearer_header_present(self):
        http = MagicMock()
        http.get.return_value = _resp(
            200, payload={"data": []},
        )
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, http=http)
            a.recommendations()
            headers = (
                http.get.call_args.kwargs["headers"]
            )
            self.assertEqual(
                headers["Authorization"],
                "Bearer tw_test",
            )
            a.close()

    def test_http_error_returns_empty(self):
        http = MagicMock()
        http.get.return_value = _resp(
            500, text="boom",
        )
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, http=http)
            self.assertEqual(a.recommendations(), [])
            self.assertIn(
                "500", a.stats()["last_error"],
            )
            a.close()

    def test_network_exception(self):
        http = MagicMock()
        http.get.side_effect = RuntimeError("net")
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, http=http)
            self.assertEqual(a.recommendations(), [])
            self.assertIn(
                "network",
                a.stats()["last_error"],
            )
            a.close()

    def test_malformed_items_skipped(self):
        http = MagicMock()
        http.get.return_value = _resp(
            200,
            payload={
                "data": [
                    "not a dict",
                    {
                        "entity_id": "c1",
                        "recommendation": "pause",
                        "confidence": "bad",
                    },
                    {
                        "entity_id": "c2",
                        "recommendation": "scale",
                        "confidence": 0.7,
                    },
                ],
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, http=http)
            recs = a.recommendations()
            ids = [r.entity_id for r in recs]
            # c1 with non-float confidence is skipped,
            # c2 survives
            self.assertIn("c2", ids)
            self.assertNotIn("c1", ids)
            a.close()

    def test_non_dict_body(self):
        http = MagicMock()
        http.get.return_value = _resp(
            200, payload="not a dict",
        )
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp, http=http)
            self.assertEqual(a.recommendations(), [])
            a.close()


class TestDisagreement(unittest.TestCase):
    def test_record_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            log = a.record_disagreement(
                decision_id="dec_1",
                moby_vote="scale",
                shopai_vote="kill",
                note="ROAS 1.2 after 3 days",
            )
            self.assertFalse(log.resolved)
            self.assertEqual(log.winner, "")
            recent = a.recent_disagreements()
            self.assertEqual(len(recent), 1)
            a.close()

    def test_record_blank_decision_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            with self.assertRaises(ValueError):
                a.record_disagreement(
                    decision_id="",
                    moby_vote="a",
                    shopai_vote="b",
                )
            a.close()

    def test_record_same_vote_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            with self.assertRaises(ValueError):
                a.record_disagreement(
                    decision_id="d",
                    moby_vote="scale",
                    shopai_vote="scale",
                )
            a.close()

    def test_update_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            a.record_disagreement(
                decision_id="d1",
                moby_vote="scale",
                shopai_vote="kill",
            )
            updated = a.update_disagreement_outcome(
                decision_id="d1",
                actual_outcome="kill",
            )
            self.assertTrue(updated)
            recent = a.recent_disagreements()
            self.assertEqual(recent[0].winner, "shopai")
            self.assertTrue(recent[0].resolved)
            a.close()

    def test_update_unknown_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            self.assertFalse(
                a.update_disagreement_outcome(
                    decision_id="nope",
                    actual_outcome="x",
                ),
            )
            a.close()

    def test_update_blank_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            with self.assertRaises(ValueError):
                a.update_disagreement_outcome(
                    decision_id="",
                    actual_outcome="x",
                )
            a.close()


class TestWinRate(unittest.TestCase):
    def test_no_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            s = a.win_rate_by_source()
            self.assertEqual(s["total_resolved"], 0)
            self.assertEqual(s["moby_win_rate"], 0.0)
            a.close()

    def test_mixed_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _build(tmp)
            # ShopAI correct
            a.record_disagreement(
                decision_id="d1",
                moby_vote="scale",
                shopai_vote="kill",
            )
            a.update_disagreement_outcome(
                decision_id="d1",
                actual_outcome="kill",
            )
            # Moby correct
            a.record_disagreement(
                decision_id="d2",
                moby_vote="scale",
                shopai_vote="kill",
            )
            a.update_disagreement_outcome(
                decision_id="d2",
                actual_outcome="scale",
            )
            # Neither correct
            a.record_disagreement(
                decision_id="d3",
                moby_vote="scale",
                shopai_vote="kill",
            )
            a.update_disagreement_outcome(
                decision_id="d3",
                actual_outcome="hold",
            )
            s = a.win_rate_by_source()
            self.assertEqual(s["total_resolved"], 3)
            self.assertEqual(s["moby_only"], 1)
            self.assertEqual(s["shopai_only"], 1)
            self.assertEqual(s["both_wrong"], 1)
            self.assertAlmostEqual(
                s["moby_win_rate"], 1 / 3,
            )
            a.close()


class TestDicts(unittest.TestCase):
    def test_rec_dict(self):
        r = MobyRecommendation(
            scope="x", entity_id="y",
            recommendation="z", confidence=0.5,
        )
        self.assertIn(
            "recommendation", r.as_dict(),
        )

    def test_log_dict(self):
        log = RLDisagreementLog(
            disagreement_id="x",
            decision_id="y",
            moby_vote="a", shopai_vote="b",
        )
        self.assertIn("winner", log.as_dict())


if __name__ == "__main__":
    unittest.main()
