"""Feature flags — runtime enable/disable for subsystems.

rollout_manager (v13-D6) stages *policy* changes through canary →
ramp → full. Feature flags solve the complementary problem:
toggle a whole *subsystem* at runtime without restarting the
daemon, and support percentage / attribute / variant gating.

FeatureFlags shapes:

  • bool flag                 — on / off
  • percentage flag           — hash-bucket entity into 0..100
  • attribute flag            — enabled only for entities whose
                                 attributes match a predicate
                                 (e.g. niche=="audio")
  • variant flag              — return one of N named variants
                                 (weighted; hash-bucketed sticky)

APIs:

  set_bool(name, enabled)
  set_percentage(name, pct)
  set_attribute(name, predicate_dict)
  set_variant(name, variants={"A": 50, "B": 50})
  is_enabled(name, entity_id=None, attrs=None) → bool
  variant(name, entity_id=None) → str | None
  pct(name) → current rollout pct
  flags() → introspection dict

Flags are read-mostly — callers check every decision. Stored in a
single JSON file (data/feature_flags.json) so owner edits are a
one-line change. Thread-safe reload.

Pure stdlib, deterministic hashing, zero LLM.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal


_STORE = Path("data/feature_flags.json")

FlagKind = Literal["bool", "percentage", "attribute", "variant"]


@dataclass
class Flag:
    name: str
    kind: FlagKind
    enabled: bool = False
    pct: float = 0.0
    attribute_predicate: dict[str, Any] = field(default_factory=dict)
    variants: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "pct": self.pct,
            "attribute_predicate": self.attribute_predicate,
            "variants": self.variants,
        }


# ── Store ───────────────────────────────────────────────────

class FeatureFlags:
    def __init__(self, store: Path | str | None = None) -> None:
        self._store = Path(store) if store else _STORE
        self._flags: dict[str, Flag] = {}
        self._lock = threading.Lock()
        self._load()

    # ── Persistence ───────────────────────────────────────

    def _load(self) -> None:
        if not self._store.exists():
            return
        try:
            raw = json.loads(self._store.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return
        with self._lock:
            self._flags = {}
            for name, payload in (raw or {}).items():
                try:
                    self._flags[name] = Flag(
                        name=name,
                        kind=payload.get("kind", "bool"),
                        enabled=bool(payload.get("enabled", False)),
                        pct=float(payload.get("pct", 0.0)),
                        attribute_predicate=dict(
                            payload.get("attribute_predicate") or {}
                        ),
                        variants=dict(
                            payload.get("variants") or {}
                        ),
                    )
                except (TypeError, ValueError):
                    continue

    def _save(self) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            n: f.as_dict() for n, f in self._flags.items()
        }
        self._store.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )

    def reload(self) -> None:
        self._load()

    # ── Setters ────────────────────────────────────────────

    def set_bool(self, name: str, enabled: bool) -> None:
        self._upsert(Flag(name=name, kind="bool", enabled=bool(enabled)))

    def set_percentage(self, name: str, pct: float) -> None:
        self._upsert(Flag(
            name=name, kind="percentage",
            pct=max(0.0, min(100.0, float(pct))),
        ))

    def set_attribute(
        self, name: str, predicate: dict[str, Any],
    ) -> None:
        self._upsert(Flag(
            name=name, kind="attribute",
            attribute_predicate=dict(predicate),
        ))

    def set_variant(
        self, name: str, variants: dict[str, float],
    ) -> None:
        if not variants:
            raise ValueError("variants dict required")
        # Normalise
        total = sum(max(0.0, float(v)) for v in variants.values())
        if total <= 0:
            raise ValueError("variant weights must sum > 0")
        norm = {k: float(v) / total for k, v in variants.items()}
        self._upsert(Flag(
            name=name, kind="variant", variants=norm,
        ))

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._flags:
                return False
            del self._flags[name]
            self._save()
            return True

    # ── Queries ────────────────────────────────────────────

    def is_enabled(
        self,
        name: str,
        entity_id: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        if flag.kind == "bool":
            return flag.enabled
        if flag.kind == "percentage":
            if flag.pct >= 100.0:
                return True
            if flag.pct <= 0.0:
                return False
            return _bucket(name, entity_id or "") < flag.pct
        if flag.kind == "attribute":
            attrs = attrs or {}
            for k, v in flag.attribute_predicate.items():
                if attrs.get(k) != v:
                    return False
            return True
        if flag.kind == "variant":
            return True
        return False

    def variant(
        self, name: str, entity_id: str | None = None,
    ) -> str | None:
        flag = self._flags.get(name)
        if flag is None or flag.kind != "variant":
            return None
        if not flag.variants:
            return None
        # Hash-bucket sticky assignment.
        h = _bucket(name, entity_id or "") / 100.0
        cum = 0.0
        for variant, weight in sorted(flag.variants.items()):
            cum += weight
            if h <= cum:
                return variant
        # floating-point tail
        return next(iter(flag.variants.keys()))

    def pct(self, name: str) -> float:
        flag = self._flags.get(name)
        return flag.pct if flag else 0.0

    def flags(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {n: f.as_dict() for n, f in self._flags.items()}

    # ── Helpers ────────────────────────────────────────────

    def _upsert(self, flag: Flag) -> None:
        if not flag.name:
            raise ValueError("flag name required")
        with self._lock:
            self._flags[flag.name] = flag
            self._save()


def _bucket(name: str, entity_id: str) -> float:
    """Stable 0..100 bucket per (flag, entity)."""
    h = hashlib.md5(f"{name}|{entity_id}".encode()).hexdigest()
    return int(h[:8], 16) % 10_000 / 100.0


# ── Singleton ────────────────────────────────────────────────

_FF_LOCK = threading.Lock()
_FLAGS: FeatureFlags | None = None


def flags() -> FeatureFlags:
    global _FLAGS
    if _FLAGS is None:
        with _FF_LOCK:
            if _FLAGS is None:
                _FLAGS = FeatureFlags()
    return _FLAGS
