"""Tests for core.adapters.obsidian.read_back — Track 6."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.adapters.obsidian.read_back import (
    ObsidianReadBack,
    ReadBackReport,
    VaultNote,
    _parse_frontmatter,
    parse_note,
)


NOTE_ACTIVE = """\
---
kind: avoid_topic
scope: global
active: true
priority: high
---
# No plastic pet toys

We've had 3 returns from plastic pet toys this quarter. Avoid.
"""


NOTE_INACTIVE = """\
---
kind: constraint
scope: niche:pet
active: false
---
# Experimental constraint
"""


NOTE_EXPIRED = """\
---
kind: risk_override
scope: global
active: true
expires: 2020-01-01
---
# Old cap
"""


NOTE_NO_FRONT = "# Just a regular note\n\nBody.\n"


NOTE_BAD_KIND = """\
---
kind: nonsense
active: true
---
# Unknown kind
"""


def _vault_with(
    tmp: Path, notes: dict[str, str],
) -> Path:
    for rel, content in notes.items():
        path = tmp / rel
        path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        path.write_text(content, encoding="utf-8")
    return tmp


class TestFrontmatterParser(unittest.TestCase):
    def test_parse_extracts_fields(self):
        front, body = _parse_frontmatter(NOTE_ACTIVE)
        self.assertEqual(front["kind"], "avoid_topic")
        self.assertEqual(front["priority"], "high")
        self.assertIn("plastic pet toys", body)

    def test_no_frontmatter(self):
        front, body = _parse_frontmatter(NOTE_NO_FRONT)
        self.assertEqual(front, {})
        self.assertEqual(body, NOTE_NO_FRONT)

    def test_quoted_values_stripped(self):
        raw = (
            "---\n"
            "kind: \"constraint\"\n"
            "scope: 'niche:pet'\n"
            "active: true\n"
            "---\n"
            "# T\n"
        )
        front, _ = _parse_frontmatter(raw)
        self.assertEqual(front["kind"], "constraint")
        self.assertEqual(front["scope"], "niche:pet")

    def test_comments_ignored(self):
        raw = (
            "---\n"
            "# a comment\n"
            "kind: constraint\n"
            "active: true\n"
            "---\nbody\n"
        )
        front, _ = _parse_frontmatter(raw)
        self.assertNotIn("# a comment", front)
        self.assertEqual(front["kind"], "constraint")


class TestParseNote(unittest.TestCase):
    def test_active_note(self):
        n = parse_note(
            path="a.md", text=NOTE_ACTIVE,
        )
        self.assertIsNotNone(n)
        self.assertEqual(n.kind, "avoid_topic")
        self.assertTrue(n.active)
        self.assertEqual(n.priority, "high")
        self.assertEqual(
            n.title, "No plastic pet toys",
        )

    def test_note_without_frontmatter_returns_none(self):
        self.assertIsNone(
            parse_note(
                path="x.md", text=NOTE_NO_FRONT,
            ),
        )

    def test_unknown_priority_coerced_to_medium(self):
        raw = (
            "---\n"
            "kind: constraint\n"
            "priority: crazy\n"
            "active: true\n"
            "---\n# T\n"
        )
        n = parse_note(path="p.md", text=raw)
        self.assertEqual(n.priority, "medium")

    def test_constraint_id_stable(self):
        n1 = parse_note(
            path="a.md", text=NOTE_ACTIVE,
        )
        n2 = parse_note(
            path="a.md", text=NOTE_ACTIVE,
        )
        self.assertEqual(
            n1.constraint_id(),
            n2.constraint_id(),
        )

    def test_constraint_id_differs_by_path(self):
        n1 = parse_note(
            path="a.md", text=NOTE_ACTIVE,
        )
        n2 = parse_note(
            path="b.md", text=NOTE_ACTIVE,
        )
        self.assertNotEqual(
            n1.constraint_id(),
            n2.constraint_id(),
        )


class TestSweep(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unavailable_vault_is_noop(self):
        rb = ObsidianReadBack(vault_path=None)
        self.assertFalse(rb.is_available())
        report = rb.sweep()
        self.assertEqual(report.scanned, 0)

    def test_active_note_applied(self):
        _vault_with(self.vault, {
            "rules/no_plastic.md": NOTE_ACTIVE,
        })
        sink = MagicMock()
        rb = ObsidianReadBack(
            vault_path=self.vault,
            constraint_sink=sink,
        )
        report = rb.sweep()
        self.assertEqual(report.applied, 1)
        sink.register.assert_called_once()
        kwargs = sink.register.call_args.kwargs
        self.assertEqual(kwargs["kind"], "avoid_topic")
        self.assertEqual(kwargs["priority"], "high")

    def test_inactive_skipped(self):
        _vault_with(self.vault, {
            "rules/inactive.md": NOTE_INACTIVE,
        })
        sink = MagicMock()
        rb = ObsidianReadBack(
            vault_path=self.vault,
            constraint_sink=sink,
        )
        report = rb.sweep()
        self.assertEqual(report.applied, 0)
        self.assertEqual(report.skipped_inactive, 1)
        sink.register.assert_not_called()

    def test_expired_skipped(self):
        _vault_with(self.vault, {
            "old.md": NOTE_EXPIRED,
        })
        sink = MagicMock()
        rb = ObsidianReadBack(
            vault_path=self.vault,
            constraint_sink=sink,
            now_fn=lambda: 1_900_000_000.0,   # 2030
        )
        report = rb.sweep()
        self.assertEqual(report.skipped_expired, 1)

    def test_unknown_kind_is_invalid(self):
        _vault_with(self.vault, {
            "bad.md": NOTE_BAD_KIND,
        })
        rb = ObsidianReadBack(
            vault_path=self.vault,
        )
        report = rb.sweep()
        self.assertEqual(report.skipped_invalid, 1)

    def test_note_without_frontmatter_skipped(self):
        _vault_with(self.vault, {
            "free.md": NOTE_NO_FRONT,
        })
        rb = ObsidianReadBack(
            vault_path=self.vault,
        )
        report = rb.sweep()
        self.assertEqual(report.skipped_invalid, 1)

    def test_sink_exception_captured(self):
        _vault_with(self.vault, {
            "active.md": NOTE_ACTIVE,
        })
        sink = MagicMock()
        sink.register.side_effect = RuntimeError("db gone")
        rb = ObsidianReadBack(
            vault_path=self.vault,
            constraint_sink=sink,
        )
        report = rb.sweep()
        self.assertEqual(report.applied, 0)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("db gone", report.errors[0])

    def test_sweep_without_sink_still_counts(self):
        _vault_with(self.vault, {
            "active.md": NOTE_ACTIVE,
        })
        rb = ObsidianReadBack(
            vault_path=self.vault,
        )
        report = rb.sweep()
        self.assertEqual(report.applied, 1)
        self.assertEqual(len(report.applied_ids), 1)

    def test_nested_folders_scanned(self):
        _vault_with(self.vault, {
            "a/active1.md": NOTE_ACTIVE,
            "b/c/active2.md": NOTE_ACTIVE,
        })
        sink = MagicMock()
        rb = ObsidianReadBack(
            vault_path=self.vault,
            constraint_sink=sink,
        )
        report = rb.sweep()
        self.assertEqual(report.applied, 2)

    def test_report_dict(self):
        rb = ObsidianReadBack(vault_path=self.vault)
        report = rb.sweep()
        d = report.as_dict()
        self.assertIn("scanned", d)


class TestVaultNoteDict(unittest.TestCase):
    def test_dict(self):
        n = VaultNote(
            path="a.md", kind="constraint",
            scope="global", active=True,
            priority="medium", expires="",
            title="T", body="B",
        )
        d = n.as_dict()
        self.assertIn("constraint_id", d)


if __name__ == "__main__":
    unittest.main()
