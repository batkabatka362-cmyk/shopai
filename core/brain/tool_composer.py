"""Tool composer — chain primitive tools into named compound tools.

ShopAI has hundreds of primitive operations (each adapter method,
each pipeline step, each memory helper). Real operators face a
different problem: "I need a tool that does X" where X is a recipe
involving 3-4 primitives. Today every such recipe has to be
hand-coded in Python.

ToolComposer lets the brain define compound tools at runtime:

    composer.compose(
        name="weekend_kill_sweep",
        recipe=[
            {"tool": "launch_evaluator.evaluate", "as": "report"},
            {"tool": "launch_evaluator.kill_all_below_roas",
             "args": {"report": "$report", "threshold": 1.2},
             "as": "killed"},
            {"tool": "oracle.notify_owner",
             "args": {"message": "$killed count killed"}},
        ],
        description="Every Friday: kill every launch under ROAS 1.2",
    )

Each compound tool is persisted at data/compound_tools.json so the
definition survives restarts. At call time:

    composer.invoke("weekend_kill_sweep", context={...}) → outputs

Steps reference prior outputs with ``$<slot>`` placeholders.
Tools can be primitive Python callables registered via
``register_primitive(name, fn)`` or compound tools themselves
(nested).

Failure isolation: if any step raises, subsequent steps are
skipped and the composer returns a partial-execution trace.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


_STORE = Path("data/compound_tools.json")
_lock = threading.Lock()


# ── Registry for primitives ─────────────────────────────────

_PRIMITIVES: dict[str, Callable[..., Any]] = {}


def register_primitive(name: str, fn: Callable[..., Any]) -> None:
    """Expose a Python callable under *name* so compound tools can
    reference it. Idempotent — second registration overwrites."""
    _PRIMITIVES[name] = fn


def list_primitives() -> list[str]:
    return sorted(_PRIMITIVES.keys())


def unregister_primitive(name: str) -> bool:
    return _PRIMITIVES.pop(name, None) is not None


# ── Data classes ────────────────────────────────────────────

@dataclass
class ExecutionStep:
    step: int
    tool: str
    status: str                    # "ok" | "failed" | "skipped"
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "duration_s": round(self.duration_s, 3),
        }


@dataclass
class ExecutionReport:
    tool: str
    status: str                    # "ok" | "failed" | "partial"
    steps: list[ExecutionStep] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status,
            "duration_s": round(self.duration_s, 3),
            "steps": [s.as_dict() for s in self.steps],
            "outputs": self.outputs,
        }


# ── Composer ────────────────────────────────────────────────

class ToolComposer:
    def __init__(self, store: Path | str | None = None) -> None:
        self._store = Path(store) if store else _STORE

    # ── Persistence ─────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if not self._store.exists():
            return {}
        try:
            return json.loads(self._store.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, state: dict[str, Any]) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        import os
        tmp = self._store.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str),
                       encoding="utf-8")
        os.replace(tmp, self._store)

    # ── CRUD ────────────────────────────────────────────────

    def compose(
        self,
        name: str,
        recipe: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        if not name or not recipe:
            raise ValueError("name + recipe required")
        # Validate every step references a known tool (primitive or other
        # compound). Unknown tools surface now, not at call time.
        for i, step in enumerate(recipe):
            tool = step.get("tool")
            if not tool:
                raise ValueError(f"step {i} missing 'tool'")
        with _lock:
            state = self._load()
            state[name] = {
                "name": name,
                "description": description,
                "recipe": recipe,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._save(state)
        return state[name]

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._load().values())

    def get(self, name: str) -> dict[str, Any] | None:
        return self._load().get(name)

    def delete(self, name: str) -> bool:
        with _lock:
            state = self._load()
            if name not in state:
                return False
            del state[name]
            self._save(state)
            return True

    # ── Invocation ──────────────────────────────────────────

    def invoke(
        self,
        name: str,
        context: dict[str, Any] | None = None,
    ) -> ExecutionReport:
        compound = self.get(name)
        if compound is None:
            return ExecutionReport(
                tool=name, status="failed",
                steps=[ExecutionStep(
                    step=0, tool="?",
                    status="failed",
                    error=f"unknown compound tool {name!r}",
                )],
            )
        started = time.monotonic()
        outputs: dict[str, Any] = dict(context or {})
        steps: list[ExecutionStep] = []
        any_failed = False
        for idx, raw_step in enumerate(compound["recipe"]):
            tool = raw_step.get("tool")
            args = raw_step.get("args") or {}
            slot = raw_step.get("as")
            if any_failed:
                steps.append(ExecutionStep(
                    step=idx, tool=tool,
                    status="skipped",
                    error="prior step failed",
                ))
                continue
            step_start = time.monotonic()
            try:
                resolved = {k: self._resolve(v, outputs)
                             for k, v in args.items()}
                fn = self._lookup(tool)
                result = fn(**resolved)
                duration = time.monotonic() - step_start
                steps.append(ExecutionStep(
                    step=idx, tool=tool,
                    status="ok",
                    output=result,
                    duration_s=duration,
                ))
                if slot:
                    outputs[slot] = result
            except Exception as exc:
                duration = time.monotonic() - step_start
                steps.append(ExecutionStep(
                    step=idx, tool=tool,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    duration_s=duration,
                ))
                any_failed = True
        elapsed = time.monotonic() - started
        all_failed = any_failed and not any(
            s.status == "ok" for s in steps
        )
        if all_failed:
            status = "failed"
        elif any_failed:
            status = "partial"
        else:
            status = "ok"
        return ExecutionReport(
            tool=name, status=status, steps=steps,
            outputs=outputs, duration_s=elapsed,
        )

    # ── Internals ───────────────────────────────────────────

    def _lookup(self, name: str) -> Callable[..., Any]:
        if name in _PRIMITIVES:
            return _PRIMITIVES[name]
        nested = self.get(name)
        if nested is not None:
            # Wrap the compound tool as a primitive so callers can
            # pass it arguments like any other.
            def call_nested(**context: Any) -> dict[str, Any]:
                report = self.invoke(name, context=context)
                return {"report": report.as_dict(),
                        "outputs": report.outputs}
            return call_nested
        raise KeyError(f"unknown tool {name!r}")

    @staticmethod
    def _resolve(value: Any, outputs: dict[str, Any]) -> Any:
        """Replace ``$slot`` placeholders with values from outputs."""
        if isinstance(value, str) and value.startswith("$"):
            key = value[1:]
            return outputs.get(key, value)
        if isinstance(value, dict):
            return {k: ToolComposer._resolve(v, outputs)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [ToolComposer._resolve(v, outputs) for v in value]
        return value


# ── Singleton ────────────────────────────────────────────────

_COMPOSER_LOCK = threading.Lock()
_COMPOSER: ToolComposer | None = None


def composer() -> ToolComposer:
    global _COMPOSER
    with _COMPOSER_LOCK:
        if _COMPOSER is None:
            _COMPOSER = ToolComposer()
    return _COMPOSER
