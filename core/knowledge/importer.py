"""Vault importer — read operator notes back into ShopAI's store.

Closes the round trip the exporter (#95) and digest (#96) opened.
The operator exports to Obsidian, annotates engine / goal pages,
runs ``shopai knowledge import <vault>``, and ShopAI persists
their notes so future engine output / digests can reference them.

How operator notes are identified
---------------------------------
The exporter writes every engine / goal page with a stable
``## Operator notes`` heading followed by an italic placeholder
line. The importer parses the YAML frontmatter to confirm the
file's ``type`` (``engine`` / ``goal``) and ``name``, then
extracts the body BELOW the heading. The auto-generated
placeholder is filtered out so operators who haven't actually
added a note don't pollute the store.

Files without the expected frontmatter (operator's own notes
unrelated to a ShopAI engine/goal) are silently skipped — the
importer is meant to be safe to point at a whole vault.

Anatomy of a parsed page
------------------------
::

    ---
    name: cart_recovery
    type: engine
    primary_goal: grow_customers
    source: shopai
    ---

    # cart_recovery
    ...
    ## Operator notes

    _Add your own observations below..._   ← placeholder, ignored

    Cart recovery seems to work best when the offer is < 10%.   ← captured
    Customers who abandoned within 1h respond better.            ← captured

    #shopai/engine ...                                            ← tag line, stripped

Storage shape comes from :mod:`core.knowledge.notes_store` —
flat ``{engine_name: notes, ...}`` dict plus a parallel
``{goal_name: notes, ...}`` written atomically in one pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from core.knowledge.notes_store import NotesStore, get_default_store

logger = get_logger("core.knowledge.importer")


_FRONTMATTER_RE = re.compile(
    r"\A---\n(.*?)\n---\n(.*)\Z",
    re.DOTALL,
)

_OPERATOR_NOTES_HEADING = "## Operator notes"

# The auto-generated placeholder text the exporter writes. When
# the body below the heading is exactly this italic line (modulo
# whitespace), treat it as "no real note" — no point persisting.
_PLACEHOLDER_FRAGMENTS = (
    "Add your own observations below",
    "Add observations or override hints here",
    "Add your own notes",
)

# Tag lines at the end of an exporter page look like
# "#shopai/engine #shopai/goal/<x>" — strip them so the
# operator's actual prose doesn't get polluted.
_TAG_LINE_RE = re.compile(r"^\s*#shopai/", re.MULTILINE)


@dataclass
class ImportSummary:
    """Counts returned by :meth:`ObsidianImporter.import_vault`."""

    engines_imported: int = 0
    goals_imported: int = 0
    files_scanned: int = 0
    files_skipped: int = 0
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engines_imported": self.engines_imported,
            "goals_imported": self.goals_imported,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
            "skipped": list(self.skipped),
        }


class ObsidianImporter:
    """Walk a vault directory and import operator notes.

    Args:
        store: Optional :class:`NotesStore` instance. Defaults to
            the module-level singleton (``data/operator_notes.json``).
            Tests pass a fresh store with a tmp path.
    """

    def __init__(self, store: NotesStore | None = None) -> None:
        self._store = store or get_default_store()

    @property
    def store(self) -> NotesStore:
        return self._store

    # ── Public API ────────────────────────────────────────────

    def import_vault(self, vault_dir: str | Path) -> ImportSummary:
        """Walk ``vault_dir`` and ingest every ShopAI-tagged page.

        Replaces the store's full content with what's found in the
        vault — entries that no longer exist there get dropped.

        Returns:
            :class:`ImportSummary` with per-bucket counts plus a
            ``skipped`` list of diagnostic reasons (one per file
            the importer chose not to ingest, with the reason).
        """
        root = Path(vault_dir).expanduser().resolve()
        summary = ImportSummary()

        if not root.exists() or not root.is_dir():
            summary.skipped.append(
                f"vault dir not found: {root}",
            )
            return summary

        engine_notes: dict[str, str] = {}
        goal_notes: dict[str, str] = {}
        engine_sources: dict[str, str] = {}
        goal_sources: dict[str, str] = {}

        for md_path in sorted(root.rglob("*.md")):
            summary.files_scanned += 1
            try:
                parsed = self._parse_file(md_path)
            except Exception as exc:  # noqa: BLE001
                summary.files_skipped += 1
                summary.skipped.append(
                    f"{md_path.name}: parse failed: {exc}",
                )
                continue

            if parsed is None:
                summary.files_skipped += 1
                continue

            kind, name, notes = parsed
            relpath = str(md_path.relative_to(root))
            if kind == "engine":
                engine_notes[name] = notes
                engine_sources[name] = relpath
                summary.engines_imported += 1
            elif kind == "goal":
                goal_notes[name] = notes
                goal_sources[name] = relpath
                summary.goals_imported += 1

        self._store.replace_all(
            engine_notes=engine_notes,
            goal_notes=goal_notes,
            source_path=str(root),
            engine_sources=engine_sources,
            goal_sources=goal_sources,
        )
        return summary

    # ── Internal parsing ──────────────────────────────────────

    def _parse_file(
        self, md_path: Path,
    ) -> tuple[str, str, str] | None:
        """Parse one markdown file. Return ``(kind, name, notes)``
        or ``None`` to skip.

        Skip rules:
          * No YAML frontmatter — operator's own notes, irrelevant.
          * ``source`` field isn't ``shopai`` — also not ours.
          * ``type`` isn't ``engine`` / ``goal``.
          * ``name`` missing.
          * No ``## Operator notes`` heading found.
          * Body under heading is empty / only the placeholder.
        """
        text = md_path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(text)
        if not match:
            return None
        front_raw, body = match.group(1), match.group(2)
        fm = _parse_frontmatter(front_raw)
        if fm.get("source") != "shopai":
            return None
        kind = fm.get("type", "").strip().lower()
        if kind not in ("engine", "goal"):
            return None
        name = fm.get("name", "").strip()
        if not name:
            return None

        notes = _extract_notes_body(body)
        if not notes:
            return None
        return kind, name, notes


# ── Module-level helpers (testable in isolation) ──────────────


def _parse_frontmatter(raw: str) -> dict[str, str]:
    """Light YAML-ish parser — handles ``key: value`` lines only.

    The exporter writes a minimal, predictable frontmatter shape;
    importing a real YAML parser as a dependency would be overkill.
    Lines without a colon are ignored. Inline ``# ...`` comments
    are stripped.
    """
    out: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        # Strip surrounding quotes if present
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]
        out[key] = value
    return out


def _extract_notes_body(body: str) -> str:
    """Find the ``## Operator notes`` section and return the
    operator's contribution (filtering placeholder + tag lines).

    Returns ``""`` when the section is missing OR contains only
    the auto-generated placeholder.
    """
    idx = body.find(_OPERATOR_NOTES_HEADING)
    if idx < 0:
        return ""
    # Everything after the heading line
    after_heading = body[idx + len(_OPERATOR_NOTES_HEADING):]
    # Trim leading newlines, then take until the next H1/H2 (or end)
    after_heading = after_heading.lstrip("\n")
    # Stop at the next ## or # heading (operator might add their
    # own subheadings, but a sibling auto-section starts at ##)
    end_match = re.search(r"^#{1,2} ", after_heading, re.MULTILINE)
    if end_match:
        section = after_heading[: end_match.start()]
    else:
        section = after_heading

    # Strip the auto-generated tag line(s) at the section foot
    section = _TAG_LINE_RE.split(section, maxsplit=1)[0]

    cleaned = section.strip()
    if not cleaned:
        return ""

    # Filter out the placeholder lines
    has_real_content = False
    for line in cleaned.splitlines():
        line_stripped = line.strip().strip("_").strip()
        if not line_stripped:
            continue
        if any(frag in line_stripped for frag in _PLACEHOLDER_FRAGMENTS):
            # Skip placeholder line
            continue
        has_real_content = True
        break

    if not has_real_content:
        return ""

    # Drop ONLY placeholder lines; keep the rest verbatim.
    kept_lines: list[str] = []
    for line in cleaned.splitlines():
        line_check = line.strip().strip("_").strip()
        if line_check and any(
            frag in line_check for frag in _PLACEHOLDER_FRAGMENTS
        ):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()
