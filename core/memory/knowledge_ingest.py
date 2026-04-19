"""External knowledge ingestion.

The structured knowledge base (v3-D4) is hand-seeded today. Real
operators absorb a steady stream of external knowledge: docs,
changelogs, blog posts, RSS feeds, markdown files on disk. This
module turns any of those into a batch of ``(subject, predicate,
object, source)`` fact triples so the KB can stay current without
code changes.

Sources supported:

  • HTTP(S) URL returning HTML or markdown
  • local markdown / txt / html file path
  • plain text string

Pipeline per document:
  1. Fetch bytes (urllib or filesystem).
  2. Strip HTML via a tolerant regex pass (no bs4 dep).
  3. Extract headed sections — the first H1/H2 becomes the
     ``subject``; each bullet / definition line becomes a
     ``(predicate, object)`` pair.
  4. Collapse to facts + write via
     ``core.memory.knowledge_base.assert_fact``.

Results are idempotent — re-ingesting the same URL / file overwrites
superseded facts. Every ingested fact carries ``source=<url|path>``
so the oracle can cite.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_UA = (
    "Mozilla/5.0 (ShopAI Knowledge Ingester) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"
)
_MAX_BYTES = 500_000           # 500 KB cap
_HEADING_RE = re.compile(r"^\s*#{1,3}\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(
    r"^\s*[-*+]\s+\*?\*?(.+?)\*?\*?\s*[:=-]\s*(.+?)\s*$",
    re.MULTILINE,
)
_DEFINITION_RE = re.compile(
    r"^\s*\*?\*?([A-Za-z][A-Za-z0-9_\- ]{1,40}?)\*?\*?\s*:\s*(.+?)\s*$",
    re.MULTILINE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SCRIPT_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE,
)
_HTML_ENTITY_RE = re.compile(r"&(?:[a-z]+|#\d+);")


@dataclass
class IngestResult:
    source: str
    subject: str
    facts_written: int = 0
    facts_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "subject": self.subject,
            "facts_written": self.facts_written,
            "facts_skipped": self.facts_skipped,
            "errors": self.errors,
        }


# ── Public API ──────────────────────────────────────────────

def ingest_url(url: str, subject: str | None = None) -> IngestResult:
    """Fetch *url*, extract facts, write them to the KB."""
    if not url or not url.startswith(("http://", "https://")):
        return IngestResult(source=url, subject=subject or "",
                            errors=["invalid URL"])
    text = _fetch_http(url)
    if text is None:
        return IngestResult(source=url, subject=subject or "",
                            errors=["fetch failed"])
    return ingest_text(text, source=url, subject=subject)


def ingest_file(path: str | Path, subject: str | None = None) -> IngestResult:
    p = Path(path)
    if not p.exists():
        return IngestResult(source=str(p), subject=subject or "",
                            errors=["file not found"])
    try:
        raw = p.read_bytes()
    except Exception as exc:
        return IngestResult(source=str(p), subject=subject or "",
                            errors=[f"read error: {exc}"])
    text = _maybe_decode(raw)
    return ingest_text(text, source=str(p), subject=subject)


def ingest_text(
    text: str,
    source: str = "inline",
    subject: str | None = None,
) -> IngestResult:
    """Parse *text* for headings + key/value facts. Writes to KB."""
    subject = subject or _extract_subject(text) or "ingested"
    result = IngestResult(source=source, subject=subject)
    if not text or len(text) < 10:
        result.errors.append("text too short")
        return result

    facts = _extract_facts(text, subject)
    if not facts:
        result.facts_skipped += 1
        return result

    try:
        from core.memory.knowledge_base import knowledge_base
        kb = knowledge_base()
    except Exception as exc:
        result.errors.append(f"kb unavailable: {exc}")
        return result

    for (subj, pred, obj) in facts:
        try:
            kb.assert_fact(subj, pred, obj, source=source)
            result.facts_written += 1
        except Exception as exc:
            result.errors.append(f"assert failed {pred}: {exc}")
            result.facts_skipped += 1
    return result


# ── Internals ───────────────────────────────────────────────

def _fetch_http(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError):
        return None
    if not raw:
        return None
    if len(raw) > _MAX_BYTES:
        raw = raw[:_MAX_BYTES]
    return _maybe_decode(raw)


def _maybe_decode(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_subject(text: str) -> str | None:
    m = _HEADING_RE.search(text)
    if m:
        return _slug(m.group(1))
    return None


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return s[:48] or "doc"


def _strip_html(text: str) -> str:
    text = _HTML_SCRIPT_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _HTML_ENTITY_RE.sub(" ", text)
    return text


def _extract_facts(
    raw: str, subject: str,
) -> list[tuple[str, str, str]]:
    """Return list of (subject, predicate, object) triples."""
    text = _strip_html(raw) if "<" in raw and ">" in raw else raw
    facts: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in _BULLET_RE.finditer(text):
        pred = _slug(match.group(1))
        obj = match.group(2).strip()[:200]
        if not pred or not obj:
            continue
        key = (subject, pred)
        if key in seen:
            continue
        seen.add(key)
        facts.append((subject, pred, _coerce(obj)))

    for match in _DEFINITION_RE.finditer(text):
        pred = _slug(match.group(1))
        obj = match.group(2).strip()[:200]
        if not pred or not obj:
            continue
        key = (subject, pred)
        if key in seen:
            continue
        seen.add(key)
        facts.append((subject, pred, _coerce(obj)))

    # Cap to 100 per doc so one page doesn't flood the KB
    return facts[:100]


def _coerce(text: str) -> Any:
    """Try to turn obvious strings into native types (int, float,
    bool) so downstream math doesn't parse them again."""
    t = text.strip()
    if t.lower() in {"true", "yes"}:
        return True
    if t.lower() in {"false", "no"}:
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t
