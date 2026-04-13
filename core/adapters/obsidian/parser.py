"""Obsidian markdown parser.

Handles the three Obsidian-specific extensions on top of
standard markdown:

  1. **YAML frontmatter** — ``---`` delimited block at the top
     of the file. Parsed with ``yaml.safe_load``.
  2. **Wikilinks** — ``[[Target]]`` or ``[[Target|display]]``.
  3. **Inline tags** — ``#tag`` anywhere in body text (merged
     with frontmatter ``tags`` list).

The parser is intentionally simple — it does NOT render markdown
to HTML or build an AST. It extracts structured metadata so the
adapter can expose notes as searchable knowledge records.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False


# ── Regex patterns ────────────────────────────────────────────

# YAML frontmatter: starts at line 1 with ``---``, ends with
# ``---`` or ``...``. Capture everything between.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?\n)(?:---|\.\.\.)[ \t]*\n",
    re.DOTALL,
)

# Wikilinks: ``[[Target]]`` or ``[[Target|alias]]``.
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Inline tags: ``#tag`` but NOT inside code blocks or URLs.
# Simplified: match ``#word`` at word boundary, exclude if
# preceded by ``&`` (HTML entities) or inside a URL.
_INLINE_TAG_RE = re.compile(r"(?<!\S)#([A-Za-z][A-Za-z0-9_/-]*)\b")


# ── Public API ────────────────────────────────────────────────


def parse_note(
    path: Path,
    vault_root: Path | None = None,
) -> dict[str, Any]:
    """Parse a single ``.md`` file into a structured dict.

    Parameters
    ----------
    path : Path
        Absolute path to the markdown file.
    vault_root : Path, optional
        If given, ``"path"`` in the result is relative to this
        root. Otherwise it's the absolute path.

    Returns
    -------
    dict with keys:
        path, title, frontmatter, tags, wikilinks, body,
        content_hash, modified_at
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()

    # ── Frontmatter ───────────────────────────────────────
    frontmatter: dict[str, Any] = {}
    body = text
    if _YAML_AVAILABLE:
        fm_match = _FRONTMATTER_RE.match(text)
        if fm_match:
            try:
                parsed = yaml.safe_load(fm_match.group(1))
                if isinstance(parsed, dict):
                    frontmatter = parsed
            except Exception:  # noqa: BLE001
                pass
            body = text[fm_match.end():]

    # ── Tags ──────────────────────────────────────────────
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, str):
        fm_tags = [t.strip() for t in fm_tags.split(",") if t.strip()]
    elif not isinstance(fm_tags, list):
        fm_tags = []
    fm_tags = [str(t) for t in fm_tags]

    inline_tags = _INLINE_TAG_RE.findall(body)
    all_tags = sorted(set(fm_tags + inline_tags))

    # ── Wikilinks ─────────────────────────────────────────
    wikilinks = sorted(set(_WIKILINK_RE.findall(text)))

    # ── Title ─────────────────────────────────────────────
    title = frontmatter.get("title", "") or ""
    if not title:
        # Use first H1 heading, or filename stem.
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped[2:].strip()
                break
        if not title:
            title = path.stem

    # ── Relative path ─────────────────────────────────────
    rel_path = str(path)
    if vault_root is not None:
        try:
            rel_path = str(path.relative_to(vault_root))
        except ValueError:
            pass

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    return {
        "path": rel_path,
        "title": str(title),
        "frontmatter": frontmatter,
        "tags": all_tags,
        "wikilinks": wikilinks,
        "body": body.strip(),
        "content_hash": content_hash,
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc,
        ).isoformat(),
    }


def search_notes(
    vault_path: Path,
    query: str,
    *,
    limit: int = 20,
    tags: list[str] | None = None,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    """Search notes in a vault by text query and optional filters.

    Scoring is intentionally simple: title match scores higher
    than body match. Results are sorted descending by score.

    Parameters
    ----------
    vault_path : Path
        Root of the Obsidian vault.
    query : str
        Search terms (case-insensitive substring match).
    limit : int
        Max results to return.
    tags : list[str], optional
        Only include notes that have ALL of these tags.
    folder : str, optional
        Only search within this subfolder.

    Returns
    -------
    list of parsed note dicts, each with an extra ``"score"`` key.
    """
    vault_path = Path(vault_path)
    query_lower = query.lower()
    results: list[tuple[float, dict[str, Any]]] = []

    search_root = vault_path
    if folder:
        search_root = vault_path / folder
        if not search_root.is_dir():
            return []

    for md_path in search_root.rglob("*.md"):
        # Skip hidden dirs (Obsidian's .obsidian, .trash, etc.)
        parts = md_path.relative_to(vault_path).parts
        if any(p.startswith(".") for p in parts):
            continue

        try:
            note = parse_note(md_path, vault_root=vault_path)
        except Exception:  # noqa: BLE001
            continue

        # Tag filter
        if tags:
            note_tags = set(note.get("tags", []))
            if not all(t in note_tags for t in tags):
                continue

        # Score
        score = 0.0
        title_lower = note["title"].lower()
        body_lower = note["body"].lower()

        if query_lower in title_lower:
            score += 10.0
            if title_lower == query_lower:
                score += 5.0
        if query_lower in body_lower:
            score += 1.0
            # Bonus for multiple occurrences (capped)
            occurrences = body_lower.count(query_lower)
            score += min(occurrences * 0.5, 5.0)

        if score > 0:
            note["score"] = score
            results.append((score, note))

    results.sort(key=lambda x: x[0], reverse=True)
    return [note for _, note in results[:limit]]


def write_note(
    vault_path: Path,
    title: str,
    body: str,
    *,
    frontmatter: dict[str, Any] | None = None,
    folder: str = "",
) -> Path:
    """Write a markdown note to the vault.

    Creates parent directories as needed. If a note with the
    same filename already exists, it is overwritten.

    Parameters
    ----------
    vault_path : Path
        Root of the Obsidian vault.
    title : str
        Note title — used as the filename (sanitised).
    body : str
        Markdown body content.
    frontmatter : dict, optional
        YAML frontmatter to prepend.
    folder : str
        Subfolder within the vault (created if missing).

    Returns
    -------
    Path to the written file.
    """
    if not _YAML_AVAILABLE:
        raise RuntimeError("pyyaml is required to write notes")

    vault_path = Path(vault_path)
    safe_name = _sanitise_filename(title)
    target_dir = vault_path / folder if folder else vault_path
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe_name}.md"

    fm = frontmatter or {}
    fm.setdefault("title", title)
    fm.setdefault("created_at", datetime.now(tz=timezone.utc).isoformat())

    content_parts = [
        "---",
        yaml.dump(fm, default_flow_style=False, allow_unicode=True).strip(),
        "---",
        "",
        body,
    ]
    target.write_text("\n".join(content_parts) + "\n", encoding="utf-8")
    return target


def list_notes(
    vault_path: Path,
    *,
    folder: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List notes from the vault, optionally filtered.

    Parameters
    ----------
    vault_path : Path
        Root of the Obsidian vault.
    folder : str, optional
        Only list notes in this subfolder.
    tags : list[str], optional
        Only include notes that have ALL of these tags.
    limit : int
        Max results.

    Returns
    -------
    list of parsed note dicts, sorted by modification time
    (newest first).
    """
    vault_path = Path(vault_path)
    search_root = vault_path / folder if folder else vault_path
    if not search_root.is_dir():
        return []

    notes: list[dict[str, Any]] = []
    for md_path in search_root.rglob("*.md"):
        parts = md_path.relative_to(vault_path).parts
        if any(p.startswith(".") for p in parts):
            continue

        try:
            note = parse_note(md_path, vault_root=vault_path)
        except Exception:  # noqa: BLE001
            continue

        if tags:
            note_tags = set(note.get("tags", []))
            if not all(t in note_tags for t in tags):
                continue

        notes.append(note)

    notes.sort(key=lambda n: n.get("modified_at", ""), reverse=True)
    return notes[:limit]


# ── Helpers ───────────────────────────────────────────────────


def _sanitise_filename(title: str) -> str:
    """Turn a note title into a safe filename (no extension).

    Strips characters that are forbidden on Windows / macOS /
    Linux and collapses whitespace into hyphens.
    """
    # Remove characters unsafe for filenames.
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    safe = re.sub(r"\s+", "-", safe.strip())
    return safe or "untitled"
