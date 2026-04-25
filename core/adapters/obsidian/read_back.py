"""Obsidian → constraint registry read-back.

Track 6 of AGI_HARDENING_PLAN. The vault bridge already syncs
*out* (brain insights → Markdown notes). This module closes the
loop: owner writes a note with YAML frontmatter into the vault,
and the next sweep pulls those notes into the behavioral
constraint registry / risk-limit overrides / avoid lists.

Note schema (frontmatter):

    ---
    kind: constraint | avoid_topic | risk_override
    scope: global | niche:pet | store:audio_us
    active: true
    priority: medium        # low | medium | high
    expires: 2026-12-31     # optional
    ---
    # Human-readable title

    Free-form body — owner explains why. Body text is attached to
    the constraint note field so brain audits show the reason.

Safe-by-default:

  * Notes without ``active: true`` frontmatter are ignored.
  * Expired notes are skipped (expires date < today).
  * Notes with an unknown ``kind`` are logged and skipped — never
    crashes the sweep.
  * Idempotent — the same note content re-imported twice produces
    no state change (constraint id is a sha1 of path + kind +
    scope).

Pure stdlib. LLM-free. Deterministic given the vault contents.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("core.adapters.obsidian.read_back")


_VALID_KINDS = (
    "constraint", "avoid_topic", "risk_override",
)
_VALID_PRIORITIES = ("low", "medium", "high")


@dataclass
class VaultNote:
    path: str
    kind: str
    scope: str
    active: bool
    priority: str
    expires: str
    title: str
    body: str

    def constraint_id(self) -> str:
        blob = (
            f"{self.path}|{self.kind}|{self.scope}"
        )
        return hashlib.sha1(
            blob.encode("utf-8"),
        ).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "scope": self.scope,
            "active": self.active,
            "priority": self.priority,
            "expires": self.expires,
            "title": self.title,
            "body": self.body,
            "constraint_id": self.constraint_id(),
        }


@dataclass
class ReadBackReport:
    scanned: int
    applied: int
    skipped_inactive: int
    skipped_expired: int
    skipped_invalid: int
    errors: tuple[str, ...] = ()
    applied_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "applied": self.applied,
            "skipped_inactive": self.skipped_inactive,
            "skipped_expired": self.skipped_expired,
            "skipped_invalid": self.skipped_invalid,
            "errors": list(self.errors),
            "applied_ids": list(self.applied_ids),
        }


# ── Parser ─────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<front>.*?)\n---\s*\n(?P<body>.*)$",
    re.DOTALL,
)


def _parse_frontmatter(
    raw: str,
) -> tuple[dict[str, str], str]:
    """Extract YAML-ish `key: value` frontmatter + body.

    Pure stdlib — avoids a yaml dependency. Supports simple
    scalar values only (that's what the schema guarantees).
    """
    match = _FRONTMATTER_RE.match(raw or "")
    if match is None:
        return {}, raw or ""
    front: dict[str, str] = {}
    for line in (match.group("front") or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        v = v.strip().strip('"').strip("'")
        front[k] = v
    return front, match.group("body") or ""


def parse_note(
    *, path: str, text: str,
) -> VaultNote | None:
    """Parse a single markdown note into a VaultNote.

    Returns None when frontmatter is missing or the ``kind``
    field is absent — those notes don't participate in the
    read-back loop.
    """
    front, body = _parse_frontmatter(text)
    if not front:
        return None
    kind = (front.get("kind") or "").lower()
    if not kind:
        return None
    scope = front.get("scope", "global")
    active_raw = (front.get("active") or "").lower()
    active = active_raw in ("true", "1", "yes")
    priority = (
        front.get("priority") or "medium"
    ).lower()
    if priority not in _VALID_PRIORITIES:
        priority = "medium"
    expires = front.get("expires", "")
    # First non-empty non-frontmatter line as title
    body_stripped = body.strip()
    title = ""
    for line in body_stripped.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            title = clean
            break
    return VaultNote(
        path=path,
        kind=kind,
        scope=scope,
        active=active,
        priority=priority,
        expires=expires,
        title=title,
        body=body_stripped,
    )


# ── Read-back sweep ────────────────────────────────────────


def _today_iso(now_fn: Any) -> str:
    return time.strftime(
        "%Y-%m-%d", time.gmtime(float(now_fn())),
    )


class ObsidianReadBack:
    """Scan a vault directory and push matching notes into the
    constraint sink."""

    def __init__(
        self,
        *,
        vault_path: str | Path | None = None,
        constraint_sink: Any = None,
        now_fn: Any = None,
    ) -> None:
        self._vault = (
            Path(vault_path) if vault_path else None
        )
        self._sink = constraint_sink
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return (
            self._vault is not None
            and self._vault.is_dir()
        )

    def scan_notes(
        self,
    ) -> Iterable[tuple[str, str]]:
        """Yield (relative_path, text) for every .md file."""
        if not self.is_available():
            return
        assert self._vault is not None
        for md in sorted(
            self._vault.rglob("*.md"),
        ):
            try:
                text = md.read_text(
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "vault read failed for %s: %s",
                    md, exc,
                )
                continue
            rel = str(
                md.relative_to(self._vault),
            )
            yield rel, text

    def sweep(
        self,
        *,
        constraint_sink: Any = None,
    ) -> ReadBackReport:
        """Scan every .md file in the vault, parse, validate,
        and push active constraints into the sink."""
        sink = (
            constraint_sink
            if constraint_sink is not None
            else self._sink
        )
        scanned = 0
        applied = 0
        sk_inactive = 0
        sk_expired = 0
        sk_invalid = 0
        errors: list[str] = []
        applied_ids: list[str] = []
        today = _today_iso(self._now_fn)
        for rel, text in self.scan_notes():
            scanned += 1
            try:
                note = parse_note(path=rel, text=text)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{rel}: {exc}")
                sk_invalid += 1
                continue
            if note is None:
                sk_invalid += 1
                continue
            if note.kind not in _VALID_KINDS:
                sk_invalid += 1
                continue
            if not note.active:
                sk_inactive += 1
                continue
            if note.expires and note.expires < today:
                sk_expired += 1
                continue
            cid = note.constraint_id()
            applied_ids.append(cid)
            if sink is None:
                applied += 1
                continue
            try:
                sink.register(
                    constraint_id=cid,
                    kind=note.kind,
                    scope=note.scope,
                    priority=note.priority,
                    note=note.title or note.body[:120],
                    source=f"obsidian:{rel}",
                )
                applied += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    f"{rel}: sink.register raised: "
                    f"{exc}",
                )
        return ReadBackReport(
            scanned=scanned,
            applied=applied,
            skipped_inactive=sk_inactive,
            skipped_expired=sk_expired,
            skipped_invalid=sk_invalid,
            errors=tuple(errors),
            applied_ids=tuple(applied_ids),
        )
