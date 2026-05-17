"""Cross-store transfer narrative format + parsing utilities.

When ``shopai transfer apply`` enqueues a PENDING action on the
target store, it writes a narrative string of the canonical form::

    Transfer suggestion: <engine>/<action_type> from <A> to <B>.
    Source had N prior successful run(s).

Or, when the operator supplied a ``--narrative`` prefix::

    <operator note>  ||  Transfer suggestion: ... from <A> to <B>. ...

That string is the ONLY persisted signal that an action originated
from a cross-store transfer (the queue schema has no
``transfer_source`` column). Four call sites parse / filter on it:

- ``shopai transfer history`` — list transfer-applied actions
- ``shopai transfer outcomes`` — measure payoff of transfers
- ``shopai daily-brief`` — surface transfer activity in morning rollup
- ``core.world_model._section_transfers`` — per-store snapshot

Pre-this-module, the format string lived in cli.py's
``_cmd_transfer_apply`` and each caller re-implemented its own LIKE
pattern + parser. A format bump (adding fields, changing word
order) silently diverged across the four call sites.

This module is the single source of truth. New callers should
import from here; existing callers can migrate incrementally.

Public surface:

- ``format_narrative(engine, action_type, from_store, to_store,
  source_run_count, operator_note="")`` — build the canonical
  narrative.
- ``parse_source_store(narrative)`` — extract the ``<A>`` source
  store; returns ``""`` on malformed input.
- ``parse_target_store(narrative)`` — extract the ``<B>`` target
  store; returns ``""`` on malformed input.
- ``parse_engine_action(narrative)`` — extract ``(engine,
  action_type)`` tuple; returns ``("", "")`` on malformed input.
- ``parse_source_run_count(narrative)`` — extract the prior-
  run count (the ``N`` in ``Source had N prior successful
  run(s)``); returns ``None`` on malformed input.
- ``parse_operator_note(narrative)`` — extract the operator-
  supplied prefix (the ``<note>`` before ``  ||  Transfer
  suggestion:``); returns ``""`` for canonical-form narratives
  without a prefix.
- ``is_transfer_narrative(narrative)`` — boolean check.
- ``SQL_LIKE_CLAUSE`` — the parameter-free WHERE clause fragment.
- ``TransferRecord`` — frozen dataclass that bundles all parsed
  fields together.
- ``record_from_narrative(narrative)`` — return a populated
  ``TransferRecord`` or ``None`` if the narrative isn't a
  transfer.

All parsers are PERMISSIVE on purpose: a future format bump
should leave existing rows surfacing (with degraded info) rather
than vanishing from operator views.
"""
from __future__ import annotations

from dataclasses import dataclass


_MARKER = "Transfer suggestion:"
_OPERATOR_SEP = "  ||  "


# Parameter-free SQL fragment for ``WHERE`` clauses. Catches both
# the canonical form and the operator-note-prefixed variant.
SQL_LIKE_CLAUSE = (
    "(narrative LIKE 'Transfer suggestion:%' "
    "OR narrative LIKE '%||  Transfer suggestion:%')"
)


def format_narrative(
    *,
    engine: str,
    action_type: str,
    from_store: str,
    to_store: str,
    source_run_count: int,
    operator_note: str = "",
) -> str:
    """Build the canonical transfer narrative.

    Args:
        engine: Source engine name (e.g. ``"loyalty"``).
        action_type: Action type being transferred.
        from_store: Source store id.
        to_store: Target store id.
        source_run_count: How many prior successful runs the
            source store has for this (engine, action_type).
        operator_note: Optional operator-supplied prefix; gets
            joined with ``  ||  ``.

    Returns:
        Narrative string suitable for ``queue.enqueue(..., narrative=...)``.
    """
    body = (
        f"{_MARKER} {engine}/{action_type} "
        f"from {from_store} to {to_store}. "
        f"Source had {source_run_count} prior successful run(s)."
    )
    note = (operator_note or "").strip()
    if note:
        return f"{note}{_OPERATOR_SEP}{body}"
    return body


def is_transfer_narrative(narrative: str) -> bool:
    """True iff ``narrative`` was written by ``transfer apply``.

    Handles both the canonical form and the operator-prefix
    variant.
    """
    if not narrative:
        return False
    return _MARKER in narrative


def parse_source_store(narrative: str) -> str:
    """Extract the source store id (``<A>``) from a narrative.

    Permissive: returns ``""`` when the narrative doesn't match
    the expected shape rather than raising. Operators viewing a
    row with degraded narrative still see the row -- they just
    lose the source-store column value.
    """
    if not narrative:
        return ""
    idx = narrative.find(_MARKER)
    if idx < 0:
        return ""
    tail = narrative[idx + len(_MARKER):]
    from_idx = tail.find(" from ")
    if from_idx < 0:
        return ""
    after_from = tail[from_idx + len(" from "):]
    to_idx = after_from.find(" to ")
    if to_idx < 0:
        return ""
    return after_from[:to_idx].strip()


def parse_target_store(narrative: str) -> str:
    """Extract the target store id (``<B>``) from a narrative.

    Permissive in the same way as :func:`parse_source_store`.
    Target is also available from the row's ``store_id`` column
    in most cases; this is the narrative-only fallback path.
    """
    if not narrative:
        return ""
    idx = narrative.find(_MARKER)
    if idx < 0:
        return ""
    tail = narrative[idx + len(_MARKER):]
    to_idx = tail.find(" to ")
    if to_idx < 0:
        return ""
    after_to = tail[to_idx + len(" to "):]
    # Target is followed by ". " (period + space) in the canonical
    # format. Permissive fallback: terminate on first period.
    end = after_to.find(".")
    if end < 0:
        return after_to.strip()
    return after_to[:end].strip()


def parse_engine_action(narrative: str) -> tuple[str, str]:
    """Extract ``(engine, action_type)`` from a narrative.

    Permissive: returns ``("", "")`` when the narrative doesn't
    follow the expected ``Transfer suggestion: <engine>/<action>``
    shape.
    """
    if not narrative:
        return ("", "")
    idx = narrative.find(_MARKER)
    if idx < 0:
        return ("", "")
    tail = narrative[idx + len(_MARKER):].lstrip()
    # "<engine>/<action_type> from ..."
    space_idx = tail.find(" ")
    if space_idx < 0:
        return ("", "")
    pair = tail[:space_idx]
    slash_idx = pair.find("/")
    if slash_idx < 0:
        return ("", "")
    return (pair[:slash_idx].strip(), pair[slash_idx + 1:].strip())


def parse_operator_note(narrative: str) -> str:
    """Extract the operator-supplied prefix from a narrative.

    When ``transfer apply --narrative "<note>"`` ran, the
    narrative is formatted as::

        <note>  ||  Transfer suggestion: ...

    This helper returns ``<note>`` (without trailing whitespace).
    For narratives WITHOUT the operator-note prefix (the
    canonical form), returns ``""``.

    Permissive: returns ``""`` on missing marker / non-transfer
    text / empty input. Never raises.

    Useful for analytics that want to surface operator
    annotations (e.g. "show transfers where the operator
    flagged a specific campaign").
    """
    if not narrative:
        return ""
    sep_idx = narrative.find(_OPERATOR_SEP)
    if sep_idx < 0:
        return ""
    # Verify what follows is actually a transfer-suggestion
    # marker -- otherwise random text containing "  ||  " would
    # match falsely.
    after_sep = narrative[sep_idx + len(_OPERATOR_SEP):]
    if _MARKER not in after_sep[:len(_MARKER) + 8]:
        return ""
    return narrative[:sep_idx].strip()


def parse_source_run_count(narrative: str) -> int | None:
    """Extract the prior-run count from a narrative.

    Canonical narrative tail:
        ``...from <A> to <B>. Source had N prior successful run(s).``

    Returns the integer ``N`` or ``None`` when the count phrase
    is missing / malformed. Useful for analytics that want to
    rank transfers by source confidence ("how proven was this
    on the source store?") without round-tripping through the
    queue to recompute.

    Permissive: never raises on malformed input.
    """
    if not narrative or _MARKER not in narrative:
        return None
    marker = "Source had "
    idx = narrative.find(marker)
    if idx < 0:
        return None
    tail = narrative[idx + len(marker):]
    # Read digits up to the first non-digit char.
    digits: list[str] = []
    for ch in tail:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


@dataclass(frozen=True)
class TransferRecord:
    """Structured view of a transfer-apply narrative.

    Bundles the four parsed fields plus the original narrative
    so callers can pass one object around instead of calling
    each parser independently. Fields use the same permissive
    semantics as the individual parsers: ``""`` / ``None`` for
    fields the narrative didn't carry.
    """

    narrative: str
    engine: str
    action_type: str
    from_store: str
    to_store: str
    source_run_count: int | None


def record_from_narrative(narrative: str) -> TransferRecord | None:
    """Parse a narrative into a :class:`TransferRecord`.

    Returns ``None`` when the narrative isn't a transfer
    narrative at all (no marker). For transfer narratives with
    partially-malformed tails, returns a record with the
    parseable fields populated and the rest blank.

    The boolean check ``record is None`` mirrors
    :func:`is_transfer_narrative`'s semantics; consumers that
    want the parsed bundle should prefer this entry point.
    """
    if not is_transfer_narrative(narrative):
        return None
    engine, action_type = parse_engine_action(narrative)
    return TransferRecord(
        narrative=narrative,
        engine=engine,
        action_type=action_type,
        from_store=parse_source_store(narrative),
        to_store=parse_target_store(narrative),
        source_run_count=parse_source_run_count(narrative),
    )
