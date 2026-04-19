"""Dialog memory tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import dialog_memory as dm


class TestExtraction(unittest.TestCase):
    def test_intent_kill(self) -> None:
        self.assertEqual(dm.extract_intent("kill audio ads"), "kill")

    def test_intent_revise(self) -> None:
        self.assertEqual(dm.extract_intent("actually scale them"), "revise")

    def test_intent_unknown(self) -> None:
        self.assertEqual(dm.extract_intent("la la la"), "unknown")

    def test_entities_amount(self) -> None:
        ents = dm.extract_entities("set budget $25 per day")
        self.assertEqual(ents.get("amount_usd"), 25.0)

    def test_entities_percent(self) -> None:
        ents = dm.extract_entities("raise prices 10%")
        self.assertEqual(ents.get("percent"), 10.0)

    def test_entities_niche(self) -> None:
        ents = dm.extract_entities("focus on fashion ads tonight")
        self.assertEqual(ents.get("niche"), "fashion")

    def test_entities_sku_hint(self) -> None:
        ents = dm.extract_entities("kill ads for SKU-1234")
        self.assertIn("sku_hint", ents)

    def test_extract_handles_noise(self) -> None:
        self.assertEqual(dm.extract_entities(""), {})


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.m = dm.DialogMemory()

    def test_blank_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record("s", "owner", "")

    def test_blank_session_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record("", "owner", "hi")

    def test_bad_role_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record("s", "robot", "hi")  # type: ignore

    def test_owner_intent_extracted(self) -> None:
        t = self.m.record("s", "owner", "kill audio ads $20")
        self.assertEqual(t.intent, "kill")
        self.assertEqual(t.entities["niche"], "audio")
        self.assertEqual(t.entities["amount_usd"], 20.0)

    def test_brain_role_doesnt_auto_extract(self) -> None:
        t = self.m.record("s", "brain", "killed audio ads")
        self.assertEqual(t.intent, "")
        self.assertEqual(t.entities, {})


class TestReferences(unittest.TestCase):
    def setUp(self) -> None:
        self.m = dm.DialogMemory()

    def test_pronoun_anchors_to_prior_entity(self) -> None:
        first = self.m.record(
            "s", "owner", "look at audio ads",
        )
        second = self.m.record(
            "s", "owner", "kill them tonight",
        )
        self.assertEqual(second.references, (first.id,))

    def test_no_pronoun_no_reference(self) -> None:
        self.m.record("s", "owner", "look at audio ads")
        plain = self.m.record("s", "owner", "publish new SKU")
        self.assertEqual(plain.references, ())

    def test_pronoun_without_prior_entity_still_links(self) -> None:
        first = self.m.record("s", "owner", "hello")
        second = self.m.record("s", "owner", "do it now")
        # Falls back to last turn since no prior entity available.
        self.assertEqual(second.references, (first.id,))


class TestHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.m = dm.DialogMemory()

    def test_history_returns_recent(self) -> None:
        for i in range(5):
            self.m.record("s", "owner", f"msg {i}")
        h = self.m.history("s", limit=3)
        self.assertEqual(len(h), 3)
        self.assertEqual(h[-1].text, "msg 4")

    def test_max_session_len_caps(self) -> None:
        m = dm.DialogMemory(max_session_len=4)
        for i in range(10):
            m.record("s", "owner", f"msg {i}")
        self.assertEqual(len(m.history("s", limit=100)), 4)

    def test_max_session_len_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            dm.DialogMemory(max_session_len=0)

    def test_latest_filters_role(self) -> None:
        self.m.record("s", "owner", "kill audio ads")
        self.m.record("s", "brain", "killed.")
        latest_owner = self.m.latest("s", role="owner")
        self.assertIn("kill", latest_owner.text)
        latest_brain = self.m.latest("s", role="brain")
        self.assertEqual(latest_brain.text, "killed.")


class TestOpenIntent(unittest.TestCase):
    def test_pending_owner_intent(self) -> None:
        m = dm.DialogMemory()
        m.record("s", "owner", "kill audio ads")
        self.assertEqual(m.open_intent("s"), "kill")

    def test_brain_responded_no_open_intent(self) -> None:
        m = dm.DialogMemory()
        m.record("s", "owner", "kill audio ads")
        m.record("s", "brain", "done")
        self.assertIsNone(m.open_intent("s"))

    def test_no_history_no_intent(self) -> None:
        m = dm.DialogMemory()
        self.assertIsNone(m.open_intent("s"))


class TestMerge(unittest.TestCase):
    def test_later_overrides_earlier(self) -> None:
        m = dm.DialogMemory()
        m.record("s", "owner", "ads $10")
        m.record("s", "owner", "actually $25")
        merged = m.merge_entities("s")
        self.assertEqual(merged["amount_usd"], 25.0)


class TestPersistence(unittest.TestCase):
    def test_writes_to_sqlite(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "d.db"
        m = dm.DialogMemory(db_path=path)
        m.record("s", "owner", "kill audio ads")
        m.close()
        # Verify SQLite file got at least one row.
        import sqlite3
        conn = sqlite3.connect(str(path))
        n = conn.execute(
            "SELECT COUNT(*) FROM dialog_turns",
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)
        tmp.cleanup()


class TestReset(unittest.TestCase):
    def test_reset_session(self) -> None:
        m = dm.DialogMemory()
        m.record("s", "owner", "msg")
        m.record("s2", "owner", "other")
        n = m.reset("s")
        self.assertEqual(n, 1)
        self.assertEqual(m.history("s"), [])
        self.assertEqual(len(m.history("s2")), 1)


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        m = dm.DialogMemory()
        m.record("s", "owner", "msg")
        m.record("s", "brain", "ok")
        m.record("s2", "owner", "hi")
        s = m.stats()
        self.assertEqual(s["sessions"], 2)
        self.assertEqual(s["total_turns"], 3)
        self.assertEqual(s["by_session"]["s"], 2)


class TestDict(unittest.TestCase):
    def test_turn_serialises(self) -> None:
        m = dm.DialogMemory()
        t = m.record("s", "owner", "kill audio ads $20")
        d = t.as_dict()
        self.assertEqual(d["intent"], "kill")
        self.assertEqual(d["entities"]["amount_usd"], 20.0)


if __name__ == "__main__":
    unittest.main()
