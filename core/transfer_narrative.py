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
- ``is_transfer_narrative(narrative)`` — boolean check.
- ``SQL_LIKE_CLAUSE`` — the parameter-free WHERE clause fragment.

All parsers are PERMISSIVE on purpose: a future format bump
should leave existing rows surfacing (with degraded info) rather
than vanishing from operator views.
"""
from __future__ import annotations


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
