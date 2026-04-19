"""Experience recorder tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.brain import experience_recorder as er


class TestSetup(unittest.TestCase):
    """Point the recorder at a temp SQLite file AND a temp vault
    for every test — never write into the real repo vault/."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._vault = tempfile.TemporaryDirectory()
        self._patch_db = patch.object(
            er, "_DB_PATH", Path(self._tmp.name) / "exp.db",
        )
        self._patch_vault = patch.dict(
            os.environ,
            {"OBSIDIAN_VAULT_PATH": self._vault.name},
        )
        self._patch_db.start()
        self._patch_vault.start()
        # Force a fresh connection for this test
        er._CONN = None

    def tearDown(self) -> None:
        if er._CONN is not None:
            try:
                er._CONN.close()
            except Exception:
                pass
            er._CONN = None
        self._patch_vault.stop()
        self._patch_db.stop()
        self._vault.cleanup()
        self._tmp.cleanup()


class TestRecordPhase(TestSetup):
    def test_phase_persisted(self) -> None:
        eid = er.record_phase(
            cycle_id="c1", name="quality_check",
            status="ok", detail={"n": 10},
        )
        self.assertTrue(eid)
        rows = er.recent(cycle_id="c1", kind="phase")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["name"], "quality_check")


class TestRecordDecision(TestSetup):
    def test_decision_persisted_and_fanout_safe(self) -> None:
        eid = er.record_decision(
            cycle_id="c1",
            context={"niche": "audio", "price": 30.0},
            chosen={"action": "scale", "confidence": 0.8},
            alternatives=[{"action": "kill"}],
            reasoning="historical win rate favours scale",
        )
        self.assertTrue(eid)
        rows = er.recent(cycle_id="c1", kind="decision")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["chosen"]["action"], "scale")

    def test_decision_without_chosen(self) -> None:
        eid = er.record_decision(
            cycle_id="c1",
            context={"x": 1}, chosen=None,
        )
        self.assertTrue(eid)


class TestRecordLLMCall(TestSetup):
    def test_llm_call_recorded(self) -> None:
        class FakeResult:
            ok = True
            adapter = "groq"
            model = "llama-3"
            cost_usd = 0.0001
            latency_ms = 123.4
            tokens_in = 10
            tokens_out = 20
            purpose = "reasoning"
            error = ""

        eid = er.record_llm_call(
            prompt="test prompt",
            result=FakeResult(),
            learnable=False,
        )
        self.assertTrue(eid)
        rows = er.recent(kind="llm_call")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["adapter"], "groq")


class TestRecordOutcome(TestSetup):
    def test_outcome_persisted(self) -> None:
        eid = er.record_outcome(
            action_id="a1",
            kpi="roas",
            value=2.5,
            source="meta_pixel",
            cycle_id="c1",
        )
        self.assertTrue(eid)
        rows = er.recent(cycle_id="c1", kind="outcome")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["value"], 2.5)


class TestRecordAssessment(TestSetup):
    def test_assessment_persisted(self) -> None:
        eid = er.record_assessment(
            cycle_id="c1",
            summary="brain ran cleanly",
            health_score=85.0,
            findings=[{"signal": "learning_rate", "level": "ok"}],
        )
        self.assertTrue(eid)
        rows = er.recent(cycle_id="c1", kind="assessment")
        self.assertEqual(len(rows), 1)


class TestRecentAndStats(TestSetup):
    def test_recent_limit_respected(self) -> None:
        for i in range(10):
            er.record_phase(
                cycle_id="c1", name=f"p{i}", status="ok",
            )
        rows = er.recent(kind="phase", limit=3)
        self.assertEqual(len(rows), 3)

    def test_stats_by_kind(self) -> None:
        er.record_phase(cycle_id="c1", name="p1", status="ok")
        er.record_decision(cycle_id="c1", context={}, chosen={"action": "x"})
        er.record_outcome(action_id="a1", kpi="r", value=1.0)
        s = er.stats()
        self.assertEqual(s["by_kind"].get("phase"), 1)
        self.assertEqual(s["by_kind"].get("decision"), 1)
        self.assertEqual(s["by_kind"].get("outcome"), 1)


class TestObsidianMirror(TestSetup):
    def test_missing_vault_silent(self) -> None:
        # No vault path set → mirror is a no-op, no exception
        with patch.dict(
            os.environ,
            {"OBSIDIAN_VAULT_PATH": "/nonexistent/path/12345"},
        ):
            eid = er.record_decision(
                cycle_id="c1",
                context={"x": 1},
                chosen={"action": "scale"},
            )
        self.assertTrue(eid)

    def test_vault_write_invoked(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        vault = Path(tmp.name)
        written_notes: list[tuple] = []

        def fake_write_note(
            vault_path, title, body,
            frontmatter=None, folder="",
        ):
            written_notes.append((title, folder))
            return vault_path / f"{title}.md"

        with patch.dict(
            os.environ, {"OBSIDIAN_VAULT_PATH": str(vault)},
        ), patch(
            "core.adapters.obsidian.parser.write_note",
            side_effect=fake_write_note,
        ):
            er.record_decision(
                cycle_id="c1",
                context={"x": 1},
                chosen={"action": "scale"},
            )
        self.assertEqual(len(written_notes), 1)
        self.assertEqual(written_notes[0][1], "Decisions")
        tmp.cleanup()


class TestGatewayIntegration(TestSetup):
    """End-to-end: LLM gateway calls experience_recorder."""

    def test_gateway_pipes_through(self) -> None:
        from core import llm_gateway as gw
        from unittest.mock import MagicMock

        fake_result = MagicMock(
            ok=True, data={"text": "hi"},
            tokens_in=5, tokens_out=7,
            adapter="groq", model="llama-3",
            error=None,
        )
        fake_router = MagicMock(
            execute=MagicMock(return_value=fake_result),
        )
        with patch("core.adapters.get_router", return_value=fake_router), \
             patch("core.adapters.Capability", MagicMock()), \
             patch("core.adapters.RouteContext", MagicMock()):
            gw.ask("hello", purpose="bulk")
        rows = er.recent(kind="llm_call")
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
