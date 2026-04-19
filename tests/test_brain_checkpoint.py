"""Brain checkpoint tests."""
from __future__ import annotations

import os
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

from core.brain import checkpoint as cp


class TestSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "data"
        self.root.mkdir()
        self.cp = cp.BrainCheckpointer(
            root=self.root,
            checkpoint_dir=self.root / "checkpoints",
            targets=("one.db", "two.json", "missing.db"),
        )
        (self.root / "one.db").write_bytes(b"one")
        (self.root / "two.json").write_text('{"x": 1}')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_snapshot_includes_present_files(self) -> None:
        s = self.cp.snapshot(label="t1")
        self.assertIn("one.db", s.targets)
        self.assertIn("two.json", s.targets)
        self.assertNotIn("missing.db", s.targets)

    def test_snapshot_writes_archive_and_meta(self) -> None:
        s = self.cp.snapshot(label="x")
        self.assertTrue(s.archive_path.exists())
        self.assertTrue(s.meta_path.exists())

    def test_snapshot_label_safe(self) -> None:
        s = self.cp.snapshot(label="bad/label spaces")
        self.assertNotIn("/", s.id)
        self.assertNotIn(" ", s.id)


class TestList(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "data"
        root.mkdir()
        self.cp = cp.BrainCheckpointer(
            root=root, checkpoint_dir=root / "checkpoints",
            targets=("one.db",),
        )
        (root / "one.db").write_bytes(b"A")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_returns_snapshots_newest_first(self) -> None:
        s1 = self.cp.snapshot(label="first")
        time.sleep(0.01)
        s2 = self.cp.snapshot(label="second")
        items = self.cp.list_snapshots()
        self.assertEqual(items[0].id, s2.id)
        self.assertEqual(items[1].id, s1.id)

    def test_get_by_id(self) -> None:
        s = self.cp.snapshot()
        fetched = self.cp.get(s.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, s.id)

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.cp.get("does-not-exist"))


class TestRestore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "data"
        self.root.mkdir()
        self.cp = cp.BrainCheckpointer(
            root=self.root, checkpoint_dir=self.root / "checkpoints",
            targets=("one.db",),
        )
        (self.root / "one.db").write_bytes(b"original")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_restore_reinstates_original(self) -> None:
        s = self.cp.snapshot(label="v1")
        # Corrupt live state
        (self.root / "one.db").write_bytes(b"corrupted")
        # Backdate the file so it predates the snapshot — freshness
        # check lets it through without force.
        old = time.time() - 10
        os.utime(self.root / "one.db", (old, old))
        result = self.cp.restore(s.id)
        self.assertIn("one.db", result.restored)
        self.assertEqual(
            (self.root / "one.db").read_bytes(), b"original",
        )

    def test_restore_skips_fresher_files(self) -> None:
        s = self.cp.snapshot(label="v1")
        # Touch live to newer mtime than snapshot
        future = time.time() + 60
        os.utime(self.root / "one.db", (future, future))
        result = self.cp.restore(s.id)
        self.assertIn("one.db", result.skipped)
        self.assertEqual(result.restored, [])

    def test_force_overrides_fresh_check(self) -> None:
        s = self.cp.snapshot(label="v1")
        (self.root / "one.db").write_bytes(b"new")
        future = time.time() + 60
        os.utime(self.root / "one.db", (future, future))
        result = self.cp.restore(s.id, force=True)
        self.assertIn("one.db", result.restored)
        self.assertTrue(result.forced)

    def test_restore_creates_pre_restore_backup(self) -> None:
        s = self.cp.snapshot(label="v1")
        old = time.time() - 10
        os.utime(self.root / "one.db", (old, old))
        result = self.cp.restore(s.id)
        self.assertIsNotNone(result.backup_path)
        self.assertTrue(result.backup_path.exists())

    def test_unknown_id_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.cp.restore("nope")


class TestPrune(unittest.TestCase):
    def test_prune_keeps_newest(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "data"
        root.mkdir()
        c = cp.BrainCheckpointer(
            root=root, checkpoint_dir=root / "checkpoints",
            targets=("one.db",),
        )
        (root / "one.db").write_bytes(b"A")
        snaps = []
        for i in range(5):
            snaps.append(c.snapshot(label=f"s{i}"))
            time.sleep(0.01)
        pruned = c.prune(keep_last=2)
        self.assertEqual(pruned, 3)
        remaining = c.list_snapshots()
        self.assertEqual(len(remaining), 2)
        tmp.cleanup()


class TestSummary(unittest.TestCase):
    def test_summary_empty(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "data"
        root.mkdir()
        c = cp.BrainCheckpointer(
            root=root, checkpoint_dir=root / "checkpoints",
            targets=("one.db",),
        )
        summary = c.summary()
        self.assertEqual(summary["count"], 0)
        self.assertIsNone(summary["newest_id"])
        tmp.cleanup()

    def test_summary_after_snapshots(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "data"
        root.mkdir()
        c = cp.BrainCheckpointer(
            root=root, checkpoint_dir=root / "checkpoints",
            targets=("one.db",),
        )
        (root / "one.db").write_bytes(b"A")
        c.snapshot()
        time.sleep(0.01)
        c.snapshot()
        summary = c.summary()
        self.assertEqual(summary["count"], 2)
        self.assertGreater(summary["total_bytes"], 0)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
