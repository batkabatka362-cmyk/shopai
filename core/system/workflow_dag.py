"""Workflow DAG — dependency-ordered task execution with retry.

tool_composer (v6-D7) chains tools linearly. Real ShopAI
workflows are *graphs*: fetch orders ∥ fetch inventory → decide
kills → (notify owner ∥ execute shopify) → record outcome. A DAG
engine runs independent branches in order, retries fails, and
fails fast when a mandatory step dies.

WorkflowDAG APIs:

  add(name, fn, deps=())      — register a task
  execute(context={})         → WorkflowReport
  visualise()                 → ordered topological string

Each task callable receives (context, inputs_dict) where
``inputs_dict`` maps dep_name → dep_return_value. The engine
topologically sorts, runs in wave order, caches each task's
return, and hands downstream tasks the upstream outputs.

Failure handling per-task:
  • retries=N              — retry on exception with backoff
  • on_fail="skip"|"abort" — when retries exhausted, skip downstream
                              (default) or abort the entire run
  • optional=True           — task failure never aborts

Pure stdlib. Deterministic. Thread-safe execution (one workflow
instance can be reused). No LLM.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


OnFail = Literal["skip", "abort"]


@dataclass
class TaskSpec:
    name: str
    fn: Callable[[dict[str, Any], dict[str, Any]], Any]
    deps: tuple[str, ...] = ()
    retries: int = 0
    on_fail: OnFail = "skip"
    optional: bool = False
    retry_backoff_s: float = 0.0


@dataclass
class TaskOutcome:
    name: str
    status: str                 # "ok" | "failed" | "skipped"
    attempts: int = 0
    duration_ms: float = 0.0
    output: Any = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 3),
            "output": self.output,
            "error": self.error,
        }


@dataclass
class WorkflowReport:
    status: Literal["ok", "partial", "aborted"]
    outcomes: list[TaskOutcome] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "order": self.order,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "outcomes": [o.as_dict() for o in self.outcomes],
        }

    def outcome(self, name: str) -> TaskOutcome | None:
        for o in self.outcomes:
            if o.name == name:
                return o
        return None


# ── DAG ────────────────────────────────────────────────────

class WorkflowDAG:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskSpec] = {}

    def add(
        self,
        name: str,
        fn: Callable[[dict[str, Any], dict[str, Any]], Any],
        deps: Iterable[str] = (),
        retries: int = 0,
        on_fail: OnFail = "skip",
        optional: bool = False,
        retry_backoff_s: float = 0.0,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("task name required")
        if name in self._tasks:
            raise ValueError(f"task {name!r} already exists")
        self._tasks[name] = TaskSpec(
            name=name, fn=fn,
            deps=tuple(deps),
            retries=int(retries),
            on_fail=on_fail,
            optional=bool(optional),
            retry_backoff_s=float(retry_backoff_s),
        )

    def tasks(self) -> list[str]:
        return list(self._tasks.keys())

    # ── Topological sort ───────────────────────────────────

    def _topo_order(self) -> list[str]:
        graph: dict[str, set[str]] = {
            n: set(self._tasks[n].deps) for n in self._tasks
        }
        # Detect unknown deps
        for name, deps in graph.items():
            for d in deps:
                if d not in self._tasks:
                    raise ValueError(
                        f"task {name!r} depends on unknown {d!r}",
                    )
        indegree: dict[str, int] = defaultdict(int)
        for n, deps in graph.items():
            indegree[n] = len(deps)
        queue: deque[str] = deque(
            n for n, d in indegree.items() if d == 0
        )
        order: list[str] = []
        while queue:
            n = queue.popleft()
            order.append(n)
            for m in self._tasks:
                if n in graph[m]:
                    graph[m].discard(n)
                    indegree[m] -= 1
                    if indegree[m] == 0:
                        queue.append(m)
        if len(order) != len(self._tasks):
            raise ValueError("cycle detected in workflow DAG")
        return order

    def visualise(self) -> str:
        order = self._topo_order()
        lines = []
        for n in order:
            spec = self._tasks[n]
            deps = ", ".join(spec.deps) if spec.deps else "(root)"
            lines.append(f"{n}  ← {deps}")
        return "\n".join(lines)

    # ── Execute ────────────────────────────────────────────

    def execute(
        self, context: dict[str, Any] | None = None,
    ) -> WorkflowReport:
        order = self._topo_order()
        ctx: dict[str, Any] = dict(context or {})
        outputs: dict[str, Any] = {}
        outcomes: list[TaskOutcome] = []
        failed: set[str] = set()
        aborted = False
        start = time.monotonic()

        for name in order:
            spec = self._tasks[name]
            # Upstream failure propagation
            if any(d in failed for d in spec.deps):
                outcomes.append(TaskOutcome(
                    name=name, status="skipped",
                    error="upstream failed",
                ))
                failed.add(name)
                continue
            inputs = {d: outputs[d] for d in spec.deps
                       if d in outputs}
            outcome = self._run_task(spec, ctx, inputs)
            outcomes.append(outcome)
            if outcome.status == "ok":
                outputs[name] = outcome.output
                continue
            # Failed
            if spec.optional:
                continue
            failed.add(name)
            if spec.on_fail == "abort":
                aborted = True
                break

        # Mark tasks we never reached due to abort
        if aborted:
            reached = {o.name for o in outcomes}
            for name in order:
                if name in reached:
                    continue
                outcomes.append(TaskOutcome(
                    name=name, status="skipped",
                    error="run aborted upstream",
                ))

        status: Literal["ok", "partial", "aborted"]
        if aborted:
            status = "aborted"
        elif failed:
            status = "partial"
        else:
            status = "ok"
        return WorkflowReport(
            status=status,
            outcomes=outcomes,
            order=order,
            elapsed_ms=(time.monotonic() - start) * 1000,
        )

    def _run_task(
        self,
        spec: TaskSpec,
        context: dict[str, Any],
        inputs: dict[str, Any],
    ) -> TaskOutcome:
        attempts = 0
        last_exc: Exception | None = None
        t = time.monotonic()
        for attempt in range(spec.retries + 1):
            attempts += 1
            try:
                out = spec.fn(context, inputs)
                duration = (time.monotonic() - t) * 1000
                return TaskOutcome(
                    name=spec.name, status="ok",
                    attempts=attempts,
                    duration_ms=duration,
                    output=out,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < spec.retries:
                    if spec.retry_backoff_s > 0:
                        time.sleep(spec.retry_backoff_s
                                    * (attempt + 1))
                    continue
                break
        duration = (time.monotonic() - t) * 1000
        return TaskOutcome(
            name=spec.name, status="failed",
            attempts=attempts, duration_ms=duration,
            error=f"{type(last_exc).__name__}: {last_exc}",
        )
