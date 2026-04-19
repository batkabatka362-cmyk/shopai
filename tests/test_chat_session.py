"""Chat session — persistence + prompt build tests with a stubbed LLM."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.brain import chat_session as cs


class _FakeResult:
    def __init__(self, text):
        self.ok = True
        self.data = {"text": text}
        self.error = None
        self.adapter = "groq"
        self.model = "llama"
        self.latency_ms = 80
        self.tokens_out = 30


class TestChatStorePersistence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cs._SESSIONS_PATH
        cs._SESSIONS_PATH = Path(self._tmp.name) / "sessions.json"

    def tearDown(self) -> None:
        cs._SESSIONS_PATH = self._orig
        self._tmp.cleanup()

    def test_create_and_roundtrip(self) -> None:
        session = cs.ChatStore.create("What's the weather?")
        session.turns.append(cs.Turn(
            role="user", text="hi", timestamp=time.time(),
        ))
        cs.ChatStore.save(session)
        loaded = cs.ChatStore.get(session.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, session.id)
        self.assertEqual(len(loaded.turns), 1)
        self.assertEqual(loaded.turns[0].text, "hi")

    def test_list_orders_by_recent_first(self) -> None:
        a = cs.ChatStore.create("first")
        time.sleep(0.01)
        b = cs.ChatStore.create("second")
        rows = cs.ChatStore.list_ids()
        self.assertEqual(rows[0]["id"], b.id)
        self.assertEqual(rows[1]["id"], a.id)


class TestSendFlow(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cs._SESSIONS_PATH
        cs._SESSIONS_PATH = Path(self._tmp.name) / "sessions.json"

    def tearDown(self) -> None:
        cs._SESSIONS_PATH = self._orig
        self._tmp.cleanup()

    def _fake_execute(self, capability, params=None, context=None, **kw):
        return _FakeResult("Sure thing, brain says [#1].")

    def test_creates_new_session_on_first_send(self) -> None:
        with patch("core.brain.oracle._pull_memories",
                   return_value=[{"id": 1, "category": "x", "action": "y",
                                  "level": 2, "score": 4.0, "content": {}}]), \
             patch("core.adapters.router.SmartRouter.execute",
                   side_effect=self._fake_execute):
            out = cs.send(None, "Why is X slow?")
        self.assertIn("session_id", out)
        self.assertEqual(out["turn_count"], 2)   # user + assistant
        self.assertIn("brain says", out["answer"])
        self.assertEqual(out["cited_ids"], [1])

    def test_second_turn_reuses_session(self) -> None:
        with patch("core.brain.oracle._pull_memories", return_value=[]), \
             patch("core.adapters.router.SmartRouter.execute",
                   side_effect=self._fake_execute):
            a = cs.send(None, "First question?")
            b = cs.send(a["session_id"], "Follow-up")
        self.assertEqual(a["session_id"], b["session_id"])
        self.assertEqual(b["turn_count"], 4)

    def test_unknown_session_returns_error(self) -> None:
        out = cs.send("chat_does_not_exist", "hi")
        self.assertIn("error", out)


class TestPromptBuilder(unittest.TestCase):
    def test_prompt_includes_last_question_and_history(self) -> None:
        s = cs.Session(id="x", created_at=0)
        s.turns = [
            cs.Turn("user", "Q1", 0), cs.Turn("assistant", "A1", 0),
            cs.Turn("user", "Q2", 0),
        ]
        prompt = cs._build_prompt(s, memories=[])
        self.assertIn("Q1", prompt)
        self.assertIn("A1", prompt)
        self.assertIn("USER: Q2", prompt)

    def test_prompt_summarises_old_turns_beyond_window(self) -> None:
        s = cs.Session(id="x", created_at=0)
        # 20 turns
        for i in range(20):
            s.turns.append(cs.Turn("user" if i % 2 == 0 else "assistant",
                                   f"msg {i}", 0))
        prompt = cs._build_prompt(s, memories=[])
        self.assertIn("earlier turns summarised", prompt)


if __name__ == "__main__":
    unittest.main()
