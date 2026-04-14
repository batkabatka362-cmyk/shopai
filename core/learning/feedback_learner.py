"""Feedback-driven learning — Option P.

Mines the down-rated chat feedback that Option H writes to
``vault/ShopAI/Feedback/`` and promotes recurring complaint themes
into ``vault/ShopAI/Learned/lessons/`` as reusable lesson notes.

Why:
    Option O surfaced feedback on the dashboard, but the AI never
    looked at it again. This module closes the loop — every recurring
    complaint becomes a persistent lesson the assistant can retrieve
    on future turns.

How it works:

1. Scan ``ShopAI/Feedback/*.md`` for notes whose frontmatter carries
   ``rating: down``.
2. Tokenise each operator-note body with a small stopword filter.
3. Cluster feedback by shared tokens; any token that recurs across
   ``min_occurrences`` (default 2) distinct feedback notes becomes a
   promotable theme.
4. For each theme, write or update
   ``ShopAI/Learned/lessons/lesson-<slug>.md`` with frontmatter
   linking back to the source feedback notes and a human-readable
   summary of the complaint pattern.
5. Re-runs are idempotent — existing lesson files get updated in
   place (new sources merged into the ``sources`` frontmatter list).

Best-effort by design: a missing vault, unreadable note, or write
failure is caught and returned in the report rather than raising.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


# Kill list mirrors the one in ``dashboard/app.py`` so the dashboard's
# "themes" view and the learner's lesson promotion agree on what counts
# as a meaningful word.
_STOPWORDS = frozenset({
    "the", "and", "but", "for", "you", "are", "was", "were", "this",
    "that", "with", "from", "have", "has", "had", "not", "its", "it's",
    "they", "their", "them", "what", "when", "where", "which", "who",
    "how", "why", "can", "does", "did", "didn", "don", "too",
    "just", "really", "very", "more", "some", "any", "all", "one",
    "two", "also", "into", "than", "then", "been", "being",
})


@dataclass
class LearnReport:
    """Outcome of a single ``FeedbackLearner.run()`` pass."""

    scanned: int = 0            # how many feedback notes we read
    down_rated: int = 0         # of those, how many were rating: down
    themes_found: int = 0       # distinct recurring themes
    lessons_written: int = 0    # new or updated lesson notes
    lessons_skipped: int = 0    # themes that didn't clear the floor
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "down_rated": self.down_rated,
            "themes_found": self.themes_found,
            "lessons_written": self.lessons_written,
            "lessons_skipped": self.lessons_skipped,
            "errors": list(self.errors),
        }


@dataclass
class _FeedbackItem:
    path: Path
    note: str
    tokens: list[str]


class FeedbackLearner:
    """Promote recurring complaint themes into vault lesson notes."""

    #: Minimum token length after lowercasing. Shorter words are
    #: almost never informative (``"fix"``, ``"bad"``, ``"the"``).
    MIN_TOKEN_LEN = 4

    def __init__(self, vault_root: str | Path):
        self.vault = Path(vault_root)
        self.feedback_dir = self.vault / "ShopAI" / "Feedback"
        self.lessons_dir = self.vault / "ShopAI" / "Learned" / "lessons"

    # ── public API ────────────────────────────────────────

    def run(self, min_occurrences: int = 2) -> LearnReport:
        """Scan feedback, cluster themes, write lessons.

        ``min_occurrences`` is the minimum number of distinct
        down-rated notes that must share a token before we promote it.
        Defaults to 2 — same threshold Option O uses for the
        dashboard "recurring themes" view.
        """
        report = LearnReport()
        if not self.feedback_dir.is_dir():
            # Nothing to mine yet — return an empty but successful
            # report so callers can run this unconditionally.
            return report

        items = self._collect_down_rated(report)
        report.down_rated = len(items)
        if not items:
            return report

        themes = self._cluster_themes(items, min_occurrences)
        report.themes_found = len(themes)

        for theme, sources in themes.items():
            try:
                written = self._emit_lesson(theme, sources)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{theme}: {exc}")
                logger.debug("lesson emit failed for %s: %s", theme, exc)
                continue
            if written:
                report.lessons_written += 1
            else:
                report.lessons_skipped += 1
        return report

    # ── scanning ──────────────────────────────────────────

    def _collect_down_rated(self, report: LearnReport) -> list[_FeedbackItem]:
        """Walk ``ShopAI/Feedback/*.md`` and keep only ``rating: down`` notes."""
        items: list[_FeedbackItem] = []
        for f in sorted(self.feedback_dir.rglob("*.md")):
            report.scanned += 1
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                report.errors.append(f"read {f.name}: {exc}")
                continue
            if self._rating(body) != "down":
                continue
            note = self._operator_note(body)
            tokens = list(set(self._tokenise(note)))
            items.append(_FeedbackItem(path=f, note=note, tokens=tokens))
        return items

    # ── clustering ────────────────────────────────────────

    def _cluster_themes(
        self,
        items: list[_FeedbackItem],
        min_occurrences: int,
    ) -> dict[str, list[Path]]:
        """Map ``token -> [feedback paths]`` keeping only recurring ones."""
        buckets: dict[str, list[Path]] = {}
        for item in items:
            for tok in item.tokens:
                buckets.setdefault(tok, []).append(item.path)

        # Dedupe paths per bucket (a note might repeat the same word),
        # then drop buckets below the threshold. Sort for stable output.
        promoted: dict[str, list[Path]] = {}
        for tok, paths in buckets.items():
            uniq = sorted({p for p in paths}, key=lambda p: p.name)
            if len(uniq) >= min_occurrences:
                promoted[tok] = uniq
        return dict(sorted(promoted.items()))

    # ── lesson emission ──────────────────────────────────

    def _emit_lesson(self, theme: str, sources: list[Path]) -> bool:
        """Create or update a lesson note for ``theme``.

        Returns True when we wrote a file, False on no-op (shouldn't
        happen in practice since the caller only passes promoted
        themes, but kept for defensive symmetry with the contract).
        """
        self.lessons_dir.mkdir(parents=True, exist_ok=True)
        slug = self._slugify(theme)
        target = self.lessons_dir / f"lesson-{slug}.md"

        # Relative paths keep the frontmatter readable in Obsidian.
        rel_sources = []
        for src in sources:
            try:
                rel_sources.append(src.relative_to(self.vault).as_posix())
            except ValueError:
                rel_sources.append(src.name)

        # If the lesson already exists, merge the source list so we
        # don't lose historical links when re-running on fresh feedback.
        merged = list(rel_sources)
        if target.exists():
            existing = self._read_existing_sources(target)
            for old in existing:
                if old not in merged:
                    merged.append(old)
        merged.sort()

        body = self._render_lesson(theme, merged)
        target.write_text(body, encoding="utf-8")
        return True

    def _read_existing_sources(self, path: Path) -> list[str]:
        """Pull the ``sources`` frontmatter list from an existing lesson."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out: list[str] = []
        inside = False
        in_sources = False
        for line in text.splitlines()[:60]:  # frontmatter only
            stripped = line.strip()
            if stripped == "---":
                if inside:
                    break
                inside = True
                continue
            if not inside:
                continue
            if stripped.startswith("sources:"):
                in_sources = True
                continue
            if in_sources:
                if stripped.startswith("- "):
                    out.append(stripped[2:].strip().strip('"'))
                else:
                    in_sources = False
        return out

    def _render_lesson(self, theme: str, sources: list[str]) -> str:
        """Assemble the markdown body for a lesson note."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        bullets = "\n".join(f'  - "{s}"' for s in sources) or "  []"
        return (
            "---\n"
            f"title: Lesson — {theme}\n"
            f"theme: {theme}\n"
            "tags: [learned, feedback-driven]\n"
            f"updated: {ts}\n"
            f"source_count: {len(sources)}\n"
            "sources:\n"
            f"{bullets}\n"
            "---\n\n"
            f"# Lesson: {theme}\n\n"
            f"Operators reported problems mentioning **{theme}** across "
            f"{len(sources)} distinct feedback note(s). When future user "
            "messages touch this topic, apply extra care:\n\n"
            "- Double-check the specific subsystem this theme relates to "
            "before answering.\n"
            "- Cite the source of any numbers you give rather than "
            "inferring from context.\n"
            "- If the operator follows up negatively again, escalate "
            "rather than repeat the same answer.\n\n"
            "## Sources\n\n"
            + "\n".join(f"- [[{s.replace('.md', '')}]]" for s in sources)
            + "\n"
        )

    # ── helpers ───────────────────────────────────────────

    @staticmethod
    def _rating(body: str) -> str:
        for line in body.splitlines()[:25]:
            stripped = line.strip().lower()
            if stripped.startswith("rating:"):
                val = stripped.split(":", 1)[1].strip()
                if val in ("up", "down"):
                    return val
        return ""

    @staticmethod
    def _operator_note(body: str) -> str:
        marker = "## Operator note"
        idx = body.find(marker)
        if idx < 0:
            # Fall back to the whole body if the caller didn't follow
            # the convention — we'd rather over-tokenise than miss a
            # recurring theme entirely.
            return body
        return body[idx + len(marker):].strip()

    @classmethod
    def _tokenise(cls, text: str) -> list[str]:
        if not text:
            return []
        pattern = r"[a-zA-Z]{" + str(cls.MIN_TOKEN_LEN) + r",}"
        words = re.findall(pattern, text.lower())
        return [w for w in words if w not in _STOPWORDS]

    @staticmethod
    def _slugify(word: str) -> str:
        # ``word`` already passed the tokeniser, so it's purely a-z,
        # but we still guard against surprises (future non-ASCII
        # themes, CJK, etc.).
        safe = re.sub(r"[^a-z0-9]+", "-", word.lower()).strip("-")
        return safe or "unnamed"


def learn_from_feedback(
    vault_root: str | Path,
    min_occurrences: int = 2,
) -> LearnReport:
    """Convenience wrapper for single-shot invocations.

    Used by the autonomous reflection hook, which doesn't want to
    manage a learner instance between cycles.
    """
    return FeedbackLearner(vault_root).run(min_occurrences=min_occurrences)
