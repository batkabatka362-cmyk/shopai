"""Look up operator context for an engine, ready to inject at
decision-review time.

The user has a round trip: export → annotate → import → notes
land in :class:`~core.knowledge.notes_store.NotesStore`. This
module is the **read** side — anything that wants to surface
the operator's wisdom at the moment of a decision (API endpoint,
CLI listing, future LLM prompt) calls
:func:`get_operator_context` and embeds the returned dict.

The shape is intentionally simple — no formatting, just the raw
note + provenance — so callers can render it the way that fits
their surface (Markdown blockquote in CLI, plain string in JSON,
prompt prefix in RAG).

Tries the engine's persisted note first, falls back to the
goal's note when no engine-specific note exists but a primary
goal is known. Returns ``None`` when nothing is available.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("core.knowledge.narrative_enricher")


def get_operator_context(
    *,
    engine: str | None = None,
    goal: str | None = None,
) -> dict[str, Any] | None:
    """Resolve the operator note for ``engine`` / ``goal``.

    Args:
        engine: Engine name (preferred lookup key). When supplied,
            the function consults the NotesStore for an engine
            note first.
        goal: Goal name (fallback). Tried when ``engine`` is
            absent or has no note.

    Returns:
        ``{"note": str, "source_kind": "engine"|"goal",
        "source_name": str, "source_path": str, "updated_at":
        float}`` or ``None`` when no note exists.
    """
    if not engine and not goal:
        return None

    store = _resolve_store()
    if store is None:
        return None

    if engine:
        try:
            entry = store.all_engine_notes().get(engine)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine notes lookup failed: %s", exc,
            )
            entry = None
        ctx = _entry_to_context(
            entry, source_kind="engine", source_name=engine,
        )
        if ctx is not None:
            return ctx

    if goal:
        try:
            entry = store.all_goal_notes().get(goal)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "goal notes lookup failed: %s", exc,
            )
            entry = None
        ctx = _entry_to_context(
            entry, source_kind="goal", source_name=goal,
        )
        if ctx is not None:
            return ctx

    return None


def enrich_action_dict(action_dict: dict[str, Any]) -> dict[str, Any]:
    """Add ``operator_context`` to a serialised :class:`ApprovalAction`.

    Pure function — returns a NEW dict; the caller's input is not
    mutated. When the engine has no persisted note the original
    dict is returned with ``operator_context: None`` so the field
    is always present (callers can render conditionally without
    needing to ``.get`` defensively).
    """
    if not isinstance(action_dict, dict):
        return action_dict
    engine = action_dict.get("engine")
    ctx = get_operator_context(engine=engine)
    out = dict(action_dict)
    out["operator_context"] = ctx
    return out


# ── Helpers ───────────────────────────────────────────────────


def _resolve_store() -> Any | None:
    try:
        from core.knowledge.notes_store import get_default_store
        return get_default_store()
    except Exception as exc:  # noqa: BLE001
        logger.debug("notes store unavailable: %s", exc)
        return None


def _entry_to_context(
    entry: Any,
    *,
    source_kind: str,
    source_name: str,
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    note = str(entry.get("notes", "") or "").strip()
    if not note:
        return None
    return {
        "note": note,
        "source_kind": source_kind,
        "source_name": source_name,
        "source_path": str(entry.get("source_path", "") or ""),
        "updated_at": entry.get("updated_at"),
    }
