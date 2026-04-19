"""Resource contention — priority scheduler over shared budgets.

rate_limiter (v13-D2) caps per-provider rates; workflow_dag
(v17-D7) executes tasks in order. Neither resolves *competing*
demand: at 09:00 the daily digest, the order-webhook consumer,
and the scheduled Meta Ads sync all want Groq tokens. Without
a scheduler the first-arriving job starves the rest or trips
the circuit breaker.

ResourceScheduler implements weighted round-robin with priority
lanes and a per-resource budget. Submitters queue jobs with:

  resource  — shared pool name (e.g. 'groq', 'shopify_rest')
  priority  — critical | high | normal | low
  cost      — estimated unit cost against the budget
  fn        — callable that consumes the resource

drain(resource, budget, max_jobs, budget_window_s) pulls jobs
for that resource, respecting priority first then FIFO within
each priority. Each drained job reserves its cost from the
budget; jobs that exceed remaining budget wait.

APIs:
  submit(resource, fn, priority, cost, metadata)  → job id
  drain(resource, budget, max_jobs)                → DrainReport
  cancel(job_id) / stats()

Pure stdlib, thread-safe, deterministic ordering.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


Priority = Literal["critical", "high", "normal", "low"]
_PRIO_RANK: dict[str, int] = {
    "critical": 0, "high": 1, "normal": 2, "low": 3,
}


@dataclass
class Job:
    job_id: str
    resource: str
    priority: Priority
    cost: float
    fn: Callable[[], Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    submitted_at: float = field(default_factory=time.time)


@dataclass
class JobResult:
    job_id: str
    status: str            # "ok" | "failed" | "skipped"
    cost_spent: float = 0.0
    duration_ms: float = 0.0
    output: Any = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "cost_spent": round(self.cost_spent, 4),
            "duration_ms": round(self.duration_ms, 3),
            "output": self.output,
            "error": self.error,
        }


@dataclass
class DrainReport:
    resource: str
    budget: float
    spent: float
    jobs_run: int
    jobs_skipped: int
    results: list[JobResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "budget": round(self.budget, 4),
            "spent": round(self.spent, 4),
            "remaining": round(self.budget - self.spent, 4),
            "jobs_run": self.jobs_run,
            "jobs_skipped": self.jobs_skipped,
            "results": [r.as_dict() for r in self.results],
        }


# ── Scheduler ──────────────────────────────────────────────

class ResourceScheduler:
    def __init__(self) -> None:
        self._queues: dict[str, dict[str, deque[Job]]] = (
            defaultdict(lambda: {p: deque() for p in _PRIO_RANK})
        )
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()

    # ── Submit ─────────────────────────────────────────────

    def submit(
        self,
        resource: str,
        fn: Callable[[], Any],
        *,
        priority: Priority = "normal",
        cost: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        resource = resource.strip()
        if not resource:
            raise ValueError("resource name required")
        if priority not in _PRIO_RANK:
            raise ValueError(f"unknown priority {priority!r}")
        if cost < 0:
            raise ValueError("cost must be ≥ 0")
        job = Job(
            job_id=uuid.uuid4().hex,
            resource=resource,
            priority=priority,
            cost=float(cost),
            fn=fn,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._queues[resource][priority].append(job)
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            self._cancelled.add(job_id)
            # Eagerly sweep queues so a drain doesn't even see it.
            for lanes in self._queues.values():
                for lane in lanes.values():
                    new_lane = deque(
                        j for j in lane if j.job_id != job_id
                    )
                    if len(new_lane) != len(lane):
                        lane.clear()
                        lane.extend(new_lane)
                        return True
        return True

    # ── Drain ──────────────────────────────────────────────

    def drain(
        self,
        resource: str,
        budget: float,
        max_jobs: int | None = None,
    ) -> DrainReport:
        report = DrainReport(
            resource=resource, budget=float(budget),
            spent=0.0, jobs_run=0, jobs_skipped=0,
        )
        if budget <= 0:
            return report
        # Collect the ordered pending list under lock
        pending: list[Job] = []
        with self._lock:
            lanes = self._queues.get(resource)
            if not lanes:
                return report
            for prio in sorted(_PRIO_RANK.keys(),
                                key=lambda k: _PRIO_RANK[k]):
                pending.extend(lanes[prio])
        remaining = float(budget)
        consumed_ids: set[str] = set()
        for job in pending:
            if job.job_id in self._cancelled:
                consumed_ids.add(job.job_id)
                report.jobs_skipped += 1
                continue
            if max_jobs is not None and report.jobs_run >= max_jobs:
                break
            if job.cost > remaining:
                # Can't afford; leave in queue for the next drain.
                report.jobs_skipped += 1
                continue
            t = time.monotonic()
            try:
                out = job.fn()
                duration = (time.monotonic() - t) * 1000
                report.results.append(JobResult(
                    job_id=job.job_id, status="ok",
                    cost_spent=job.cost,
                    duration_ms=duration,
                    output=out,
                ))
                remaining -= job.cost
                report.spent += job.cost
                report.jobs_run += 1
            except Exception as exc:
                duration = (time.monotonic() - t) * 1000
                report.results.append(JobResult(
                    job_id=job.job_id, status="failed",
                    cost_spent=0.0, duration_ms=duration,
                    error=f"{type(exc).__name__}: {exc}",
                ))
                # Failure still counts as 'processed' — pop from queue.
            consumed_ids.add(job.job_id)
        # Remove consumed jobs from queues
        with self._lock:
            for prio in _PRIO_RANK:
                lane = self._queues[resource][prio]
                new_lane = deque(
                    j for j in lane if j.job_id not in consumed_ids
                )
                lane.clear()
                lane.extend(new_lane)
        return report

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {"queues": {}}
            for resource, lanes in self._queues.items():
                out["queues"][resource] = {
                    prio: len(lane) for prio, lane in lanes.items()
                }
            out["cancelled"] = len(self._cancelled)
        return out

    def pending_count(self, resource: str) -> int:
        with self._lock:
            lanes = self._queues.get(resource)
            if not lanes:
                return 0
            return sum(len(lane) for lane in lanes.values())
