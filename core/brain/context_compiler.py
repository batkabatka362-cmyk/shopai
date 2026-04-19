"""Context compiler — unified Context object across brain modules.

Every module invented its own context dict: world_model's
``Context(niche, price_band, ...)``, tree_search's ``State(cash_
band, open_launches, ...)``, surprise's signature string, policy_
library's ``applicability`` dict, self_prompt's ``Situation``.

Callers had to construct all of them by hand and keep them in
sync. Inevitably they drifted — a cycle would update world_model
with niche=audio but query policies with niche=Audio (case
mismatch) and surprise with no niche at all.

ContextCompiler takes a raw observation dict and emits a
CompiledContext that carries *every* downstream shape, all derived
from one normalised source:

  • features       — canonical lowercased keys for world_model,
                     reward_model, epistemic, habit.
  • world_context  — core.brain.world_model.Context
  • tree_state     — core.brain.tree_search.State
  • signature      — stable string for surprise + habit + dedup
  • applicability  — predicate dict for policy_library.propose
  • situation      — core.brain.self_prompt.Situation
  • enrichment     — anything else the caller added (raw obs
                     passthroughs)

All derivations run on one canonicalise step: string fields lower-
cased + stripped, numeric fields float-coerced, missing keys back-
filled from sensible defaults. Idempotent — re-running on an
already-compiled context returns the same object.

Pure Python, no I/O.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.context_compiler")


_DEFAULTS: dict[str, Any] = {
    "niche": "unknown",
    "price_band": "mid",
    "margin_band": "mid",
    "copy_tone": "friendly",
    "action": "",
    "cash_band": "mid",
    "open_launches": 0,
}


@dataclass
class CompiledContext:
    features: dict[str, Any] = field(default_factory=dict)
    world_context: Any = None
    tree_state: Any = None
    signature: str = ""
    applicability: dict[str, Any] = field(default_factory=dict)
    situation: Any = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "features": self.features,
            "world_context": (
                self.world_context.as_tuple()
                if hasattr(self.world_context, "as_tuple")
                else self.world_context
            ),
            "tree_state": (
                self.tree_state.__dict__
                if self.tree_state is not None else None
            ),
            "signature": self.signature,
            "applicability": self.applicability,
            "situation": (
                self.situation.__dict__
                if self.situation is not None else None
            ),
            "raw": self.raw,
        }


# ── Normalisation ──────────────────────────────────────────

def _canonicalise(obs: dict[str, Any]) -> dict[str, Any]:
    canon: dict[str, Any] = {}
    for k, v in obs.items():
        key = str(k).strip().lower()
        if isinstance(v, str):
            canon[key] = v.strip().lower() or None
        else:
            canon[key] = v
    # Drop None-valued keys so defaults kick in.
    return {k: v for k, v in canon.items() if v is not None}


def _with_defaults(canon: dict[str, Any]) -> dict[str, Any]:
    out = {**_DEFAULTS, **canon}
    # Coerce numeric-ish fields safely.
    for numeric in ("open_launches", "days_elapsed"):
        if numeric in out:
            try:
                out[numeric] = int(float(out[numeric]))
            except (TypeError, ValueError):
                out[numeric] = 0
    return out


def _features(canon: dict[str, Any]) -> dict[str, Any]:
    keys = ("niche", "price_band", "margin_band", "copy_tone", "action")
    return {k: canon[k] for k in keys if canon.get(k)}


def _signature(canon: dict[str, Any]) -> str:
    keys = ("niche", "price_band", "margin_band", "copy_tone",
             "action", "kind")
    parts = sorted(
        (k, str(canon[k])) for k in keys if canon.get(k)
    )
    joined = "|".join(f"{k}={v}" for k, v in parts)
    if not joined:
        return "context|empty"
    # Stable short suffix so long strings don't blow up indexes.
    suffix = hashlib.sha1(joined.encode()).hexdigest()[:8]
    return f"{joined}#{suffix}"


def _applicability(canon: dict[str, Any]) -> dict[str, Any]:
    """Predicate dict policy_library consumes."""
    keys = ("niche", "price_band", "margin_band", "copy_tone")
    return {k: canon[k] for k in keys if canon.get(k)}


# ── Compile ────────────────────────────────────────────────

def compile_context(obs: dict[str, Any]) -> CompiledContext:
    """Main entry. Safe on empty input."""
    if obs is None:
        obs = {}
    if isinstance(obs, CompiledContext):
        return obs
    canon = _with_defaults(_canonicalise(obs))

    # Lazy imports so a missing subsystem doesn't break compilation.
    world_context = None
    tree_state = None
    situation = None
    try:
        from core.brain.world_model import Context as WContext
        world_context = WContext(
            niche=canon["niche"],
            price_band=canon["price_band"],
            margin_band=canon["margin_band"],
            copy_tone=canon["copy_tone"],
        )
    except Exception as exc:
        logger.debug("world_context compile failed: %s", exc)
    try:
        from core.brain.tree_search import State as TState
        tree_state = TState(
            cash_band=canon.get("cash_band", "mid"),
            open_launches=int(canon.get("open_launches", 0)),
            days_elapsed=int(canon.get("days_elapsed", 0)),
            niche=canon["niche"],
            price_band=canon["price_band"],
            margin_band=canon["margin_band"],
            copy_tone=canon["copy_tone"],
        )
    except Exception as exc:
        logger.debug("tree_state compile failed: %s", exc)
    try:
        from core.brain.self_prompt import Situation
        situation = Situation(
            kills_last_7d=int(canon.get("kills_last_7d", 0)),
            scales_last_7d=int(canon.get("scales_last_7d", 0)),
            calibration_hit_rate=float(
                canon.get("calibration_hit_rate", 0.7),
            ),
        )
    except Exception as exc:
        logger.debug("situation compile failed: %s", exc)

    return CompiledContext(
        features=_features(canon),
        world_context=world_context,
        tree_state=tree_state,
        signature=_signature(canon),
        applicability=_applicability(canon),
        situation=situation,
        raw=canon,
    )


# ── Merging ─────────────────────────────────────────────────

def merge(
    base: dict[str, Any] | CompiledContext,
    extra: dict[str, Any],
) -> CompiledContext:
    """Overlay ``extra`` onto ``base`` then recompile. Useful when
    a cycle pipeline enriches the context as it runs."""
    if isinstance(base, CompiledContext):
        base_dict = dict(base.raw)
    else:
        base_dict = dict(base or {})
    base_dict.update(extra or {})
    return compile_context(base_dict)
