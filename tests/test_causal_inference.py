"""Causal inference — scoring + ranking tests without touching sqlite."""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from core.brain import causal_inference as ci


class TestSummaryFor(unittest.TestCase):
    def test_names_top_action(self) -> None:
        entries = [
            (1, 3.0, 100.0, "price_delta"),
            (2, 3.0, 101.0, "price_delta"),
            (3, 3.0, 102.0, "trend_flip"),
        ]
        summary = ci._summary_for("competitor", entries)
        self.assertIn("price_delta", summary)
        self.assertIn("× 2", summary)

    def test_empty_actions(self) -> None:
        summary = ci._summary_for("launch", [(1, 2.0, 0.0, "")])
        self.assertIn("1 launch events", summary)


class TestPopulateLogic(unittest.TestCase):
    def test_ranked_by_strength(self) -> None:
        report = ci.CausalReport(
            target_kind="launch", target_id="x",
            anchor_ts=time.time(),
        )

        class FakeCursor:
            def __init__(self, rows): self._rows = rows
            def execute(self, *a, **k): return self
            def fetchall(self): return self._rows

        class FakeConn:
            def __init__(self, rows): self._cur = FakeCursor(rows)
            def cursor(self): return self._cur
            def close(self): pass

        now = report.anchor_ts
        rows = [
            # (id, category, action, content_json, score, timestamp)
            (1, "competitor", "price_delta", "{}", 4.0, now - 3600),
            (2, "competitor", "price_delta", "{}", 4.0, now - 7200),
            (3, "trend", "down", "{}", 3.0, now - 86400 * 6),  # far from anchor
            (4, "anomaly", "spike", "{}", 5.0, now - 900),
        ]
        # Redirect _DB_PATH to a real temp file so .exists() returns True
        # without us monkey-patching PosixPath.
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.close()
        try:
            orig = ci._DB_PATH
            ci._DB_PATH = type(orig)(tmp.name)
            with patch("sqlite3.connect", return_value=FakeConn(rows)):
                ci._populate(report)
        finally:
            ci._DB_PATH = orig
            os.unlink(tmp.name)

        cats = [c.category for c in report.candidates]
        self.assertIn("competitor", cats)
        self.assertIn("anomaly", cats)
        self.assertIn("trend", cats)
        # Competitor has 2 entries × 4.0 × fresh recency → outranks
        # anomaly's single 5.0 event; trend is 6 days out so weakest.
        self.assertEqual(report.candidates[0].category, "competitor")
        self.assertEqual(report.candidates[-1].category, "trend")
        self.assertEqual(len(report.candidates), 3)


class TestPublicAPI(unittest.TestCase):
    def test_missing_launch_returns_empty(self) -> None:
        with patch.object(ci, "_launch_anchor", return_value=None):
            report = ci.investigate_launch("no_such_launch")
        self.assertEqual(report.candidates, [])
        self.assertEqual(report.anchor_ts, 0.0)

    def test_investigate_event_uses_provided_ts(self) -> None:
        with patch.object(ci, "_populate"):
            report = ci.investigate_event(1_000_000.0, label="unit")
        self.assertEqual(report.target_id, "unit")
        self.assertEqual(report.anchor_ts, 1_000_000.0)


if __name__ == "__main__":
    unittest.main()
