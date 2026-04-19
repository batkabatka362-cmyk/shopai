"""Meta-cognitive reflection — signal probe + scoring tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from core.brain import metacognition as mc


class TestScoring(unittest.TestCase):
    def test_all_ok_means_full_health(self) -> None:
        findings = [
            mc.Finding("learning_rate", "ok", 5, 3, ""),
            mc.Finding("feedback", "ok", 0.8, 0.5, ""),
        ]
        self.assertEqual(mc._score(findings), 100.0)

    def test_warnings_deduct_ten(self) -> None:
        findings = [
            mc.Finding("learning_rate", "warning", 1, 3, ""),
            mc.Finding("feedback", "ok", 0.8, 0.5, ""),
        ]
        self.assertEqual(mc._score(findings), 90.0)

    def test_critical_deducts_more(self) -> None:
        findings = [
            mc.Finding("learning_rate", "critical", 0, 3, ""),
        ]
        self.assertEqual(mc._score(findings), 75.0)

    def test_score_floors_at_zero(self) -> None:
        findings = [mc.Finding("x", "critical", 0, 0, "")] * 10
        self.assertEqual(mc._score(findings), 0.0)


class TestReflectFlow(unittest.TestCase):
    def test_empty_dbs_return_report_without_findings(self) -> None:
        # Redirect module-level paths to guaranteed-non-existent files
        from pathlib import Path
        orig_mi, orig_sk = mc._MI_DB, mc._SKILLS_DB
        mc._MI_DB = Path("/tmp/shopai_does_not_exist_mi.db")
        mc._SKILLS_DB = Path("/tmp/shopai_does_not_exist_sk.db")
        try:
            with patch.object(mc, "_persist"):
                report = mc.reflect()
        finally:
            mc._MI_DB, mc._SKILLS_DB = orig_mi, orig_sk
        self.assertEqual(report.findings, [])
        self.assertEqual(report.health, 100.0)

    def test_report_serialises_to_dict(self) -> None:
        r = mc.ReflectionReport(
            health=80,
            findings=[mc.Finding("x", "warning", 1, 2, "detail")],
            ts=123.0,
        )
        d = r.as_dict()
        self.assertEqual(d["health"], 80)
        self.assertEqual(d["worst"], "warning")
        self.assertEqual(d["findings"][0]["signal"], "x")


class TestFeedbackBalance(unittest.TestCase):
    def _probe(self, actions: list[str]) -> mc.ReflectionReport:
        class FakeCur:
            def execute(self_inner, *a, **k): return self_inner
            def fetchall(self_inner): return [(a,) for a in actions]
        class FakeConn:
            def __init__(self_inner): self_inner._cur = FakeCur()
            def cursor(self_inner): return self_inner._cur
            def close(self_inner): pass
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.close()
        report = mc.ReflectionReport()
        orig = mc._MI_DB
        from pathlib import Path
        mc._MI_DB = Path(tmp.name)
        try:
            with patch("sqlite3.connect", return_value=FakeConn()):
                mc._check_feedback_balance(report)
        finally:
            mc._MI_DB = orig
            import os
            os.unlink(tmp.name)
        return report

    def test_majority_up_is_ok(self) -> None:
        report = self._probe(["up_vote"] * 4 + ["down_vote"])
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].level, "ok")

    def test_majority_down_is_critical(self) -> None:
        report = self._probe(["up_vote"] + ["down_vote"] * 4)
        self.assertEqual(report.findings[0].level, "critical")


if __name__ == "__main__":
    unittest.main()
