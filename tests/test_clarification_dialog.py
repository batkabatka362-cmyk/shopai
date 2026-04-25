"""Clarification dialog tests."""
from __future__ import annotations

import unittest

from core.brain import clarification_dialog as cd


class TestDetect(unittest.TestCase):
    def test_blank_text_raises(self) -> None:
        dlg = cd.ClarificationDialog()
        with self.assertRaises(ValueError):
            dlg.find_ambiguities("")

    def test_no_ambiguity(self) -> None:
        dlg = cd.ClarificationDialog()
        findings = dlg.find_ambiguities(
            "set product p1 price to 29.99 dollars",
        )
        # Pronoun "it"/"this" not present, no missing slot required.
        self.assertEqual(findings, [])

    def test_missing_required_slot(self) -> None:
        dlg = cd.ClarificationDialog(
            required_slots=("budget", "store"),
        )
        findings = dlg.find_ambiguities("launch the ad")
        kinds = {f.kind for f in findings}
        self.assertIn("missing_slot", kinds)

    def test_provided_slot_not_flagged(self) -> None:
        dlg = cd.ClarificationDialog(required_slots=("budget",))
        findings = dlg.find_ambiguities(
            "launch the ad", provided_slots={"budget": 20},
        )
        kinds = {f.kind for f in findings}
        self.assertNotIn("missing_slot", kinds)

    def test_unresolved_pronoun(self) -> None:
        dlg = cd.ClarificationDialog()
        findings = dlg.find_ambiguities("kill it")
        kinds = {f.kind for f in findings}
        self.assertIn("unresolved_pronoun", kinds)

    def test_resolver_suppresses_pronoun(self) -> None:
        dlg = cd.ClarificationDialog(
            context_resolver=lambda p: True,
        )
        findings = dlg.find_ambiguities("kill it")
        kinds = {f.kind for f in findings}
        self.assertNotIn("unresolved_pronoun", kinds)

    def test_missing_unit(self) -> None:
        dlg = cd.ClarificationDialog()
        findings = dlg.find_ambiguities("bump budget 10")
        kinds = {f.kind for f in findings}
        self.assertIn("missing_unit", kinds)

    def test_unit_present_not_flagged(self) -> None:
        dlg = cd.ClarificationDialog()
        findings = dlg.find_ambiguities("bump budget 10 percent")
        kinds = {f.kind for f in findings}
        self.assertNotIn("missing_unit", kinds)

    def test_scope_ambiguous(self) -> None:
        dlg = cd.ClarificationDialog()
        findings = dlg.find_ambiguities("update all products")
        kinds = {f.kind for f in findings}
        self.assertIn("scope_ambiguous", kinds)


class TestPriority(unittest.TestCase):
    def test_priority_order(self) -> None:
        dlg = cd.ClarificationDialog(required_slots=("budget",))
        findings = dlg.find_ambiguities("launch it")
        # missing_slot priority 1, pronoun priority 2 → slot first
        self.assertEqual(findings[0].priority, 1)
        self.assertLessEqual(
            findings[0].priority, findings[-1].priority,
        )


class TestDraft(unittest.TestCase):
    def test_draft_returns_request(self) -> None:
        dlg = cd.ClarificationDialog()
        request = dlg.draft("kill it")
        self.assertIsNotNone(request)
        self.assertEqual(request.status, "open")

    def test_draft_unambiguous_returns_none(self) -> None:
        dlg = cd.ClarificationDialog()
        request = dlg.draft("set price to 29 dollars")
        self.assertIsNone(request)


class TestLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.dlg = cd.ClarificationDialog()
        self.request = self.dlg.draft("kill it")

    def test_answer(self) -> None:
        r = self.dlg.answer(
            self.request.id, "campaign CMP-42",
        )
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.answer, "campaign CMP-42")

    def test_blank_answer_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.dlg.answer(self.request.id, "")

    def test_dismiss(self) -> None:
        r = self.dlg.dismiss(self.request.id)
        self.assertEqual(r.status, "dismissed")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.dlg.answer("nope", "x")

    def test_answer_after_answer_raises(self) -> None:
        self.dlg.answer(self.request.id, "x")
        with self.assertRaises(ValueError):
            self.dlg.answer(self.request.id, "y")


class TestQueries(unittest.TestCase):
    def test_open_requests(self) -> None:
        dlg = cd.ClarificationDialog()
        r1 = dlg.draft("kill it")
        r2 = dlg.draft("bump budget 10")
        open_list = dlg.open_requests()
        self.assertEqual(len(open_list), 2)
        ids = {r.id for r in open_list}
        self.assertIn(r1.id, ids)
        self.assertIn(r2.id, ids)

    def test_get_open_and_closed(self) -> None:
        dlg = cd.ClarificationDialog()
        r = dlg.draft("kill it")
        self.assertIsNotNone(dlg.get(r.id))
        dlg.answer(r.id, "x")
        self.assertIsNotNone(dlg.get(r.id))

    def test_get_unknown_returns_none(self) -> None:
        dlg = cd.ClarificationDialog()
        self.assertIsNone(dlg.get("nope"))


class TestStats(unittest.TestCase):
    def test_stats(self) -> None:
        dlg = cd.ClarificationDialog(required_slots=("a", "b"))
        dlg.draft("kill it")
        s = dlg.stats()
        self.assertEqual(s["open"], 1)
        self.assertEqual(s["required_slots"], 2)


class TestDict(unittest.TestCase):
    def test_finding_serialises(self) -> None:
        dlg = cd.ClarificationDialog()
        findings = dlg.find_ambiguities("kill it")
        d = findings[0].as_dict()
        self.assertIn("question", d)

    def test_request_serialises(self) -> None:
        dlg = cd.ClarificationDialog()
        r = dlg.draft("kill it")
        d = r.as_dict()
        self.assertIn("finding", d)
        self.assertEqual(d["status"], "open")


if __name__ == "__main__":
    unittest.main()
