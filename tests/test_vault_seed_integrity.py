"""Integrity tests for the checked-in Obsidian vault.

The ``vault/`` directory ships a seed knowledge base — MOCs, core
concepts, adapter catalog, ADRs, wins. These tests make sure the
seed stays machine-readable and well-connected:

  * Every ``.md`` file parses with ``parse_note``.
  * No note has a malformed YAML frontmatter.
  * Every wikilink resolves to a real note — except for a small
    allow-list of intentional placeholders (template stubs,
    literal doc examples).

If a contributor adds a broken link or a typo in frontmatter,
these tests catch it before it pollutes the graph.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.adapters.obsidian.parser import parse_note


REPO_ROOT = Path(__file__).resolve().parent.parent
VAULT = REPO_ROOT / "vault"

# Wikilinks that exist on purpose without a target:
#   - Template stubs (get replaced when the operator instantiates)
#   - Literal docs (e.g. "Wikilinks look [[like this]]")
ALLOWED_UNRESOLVED = {
    "alt name",            # YAML Frontmatter example
    "other note",          # YAML Frontmatter example
    "like this",           # Obsidian Integration doc example
    "related concept",     # template placeholder
    "related decision",    # template placeholder
    "related error",       # template placeholder
    "related win",         # template placeholder
}


def _all_notes() -> list[Path]:
    return sorted(VAULT.rglob("*.md"))


def _title_index() -> set[str]:
    """Lower-cased set of every note's title AND filename stem."""
    titles: set[str] = set()
    for f in _all_notes():
        try:
            n = parse_note(f, VAULT)
            titles.add(str(n.get("title", "")).lower())
        except Exception:  # noqa: BLE001
            pass
        titles.add(f.stem.lower())
    return titles


@pytest.mark.skipif(not VAULT.exists(), reason="vault/ not present")
class TestVaultSeedIntegrity:
    """Checked-in vault must stay parseable and well-linked."""

    def test_vault_not_empty(self):
        assert len(_all_notes()) > 0, "vault/ has no markdown files"

    def test_has_root_moc(self):
        assert (VAULT / "00 Home.md").exists(), "missing 00 Home.md MOC"

    def test_every_note_parses(self):
        errors: list[str] = []
        for f in _all_notes():
            try:
                parse_note(f, VAULT)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{f.relative_to(VAULT)}: {exc}")
        assert not errors, "\n".join(errors)

    def test_every_wikilink_resolves(self):
        titles = _title_index()
        broken: list[str] = []
        for f in _all_notes():
            n = parse_note(f, VAULT)
            for target in n["wikilinks"]:
                key = target.lower()
                if key in titles or key in ALLOWED_UNRESOLVED:
                    continue
                broken.append(f"{f.relative_to(VAULT)} → [[{target}]]")
        assert not broken, (
            "Unresolved wikilinks (add to ALLOWED_UNRESOLVED if "
            "intentional):\n" + "\n".join(broken)
        )

    def test_expected_mocs_exist(self):
        expected = [
            "00 Home.md",
            "Concepts/_Concepts MOC.md",
            "Knowledge/_Adapters Catalog.md",
            "Knowledge/_Capabilities MOC.md",
            "ShopAI/Learned/README.md",
        ]
        missing = [p for p in expected if not (VAULT / p).exists()]
        assert not missing, f"missing MOC/README: {missing}"

    def test_core_concepts_present(self):
        """Each core subsystem has a Concept note."""
        must_have = [
            "Brain.md", "Memory.md", "Controller Loop.md",
            "Capability Routing.md", "Reflection Hook.md",
            "Adapter Hooks.md",
        ]
        missing = [
            p for p in must_have
            if not (VAULT / "Concepts" / p).exists()
        ]
        assert not missing, f"missing core concepts: {missing}"

    def test_adr_notes_present(self):
        """Key architecture decisions are recorded."""
        must_have = [
            "Use Obsidian for Memory.md", "Use HubSpot for CRM.md",
            "Why Smart Router.md", "Use n8n over Zapier.md",
            "Best-Effort Adapter Hooks.md",
        ]
        missing = [
            p for p in must_have
            if not (VAULT / "Decisions" / p).exists()
        ]
        assert not missing, f"missing ADRs: {missing}"

    def test_every_note_has_title_and_tags(self):
        """Frontmatter must carry ``title`` and ``tags`` at minimum."""
        bad: list[str] = []
        for f in _all_notes():
            n = parse_note(f, VAULT)
            fm = n.get("frontmatter", {})
            if not fm.get("title"):
                bad.append(f"{f.relative_to(VAULT)}: missing title")
            if not n.get("tags"):
                bad.append(f"{f.relative_to(VAULT)}: missing tags")
        assert not bad, "\n".join(bad)
