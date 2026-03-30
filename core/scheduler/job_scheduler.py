"""JobScheduler — cron-like scheduler for recurring engine tasks."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id
from .cron_parser import CronParser
from .job_queue import JobQueue

logger = get_logger("scheduler")


@dataclass
class Job:
    """A scheduled job."""
    job_id: str
    engine_name: str
    params: dict[str, Any]
    schedule: str  # cron expression or preset
    enabled: bool = True
    description: str = ""
    last_run: float | None = None
    run_count: int = 0
    error_count: int = 0
    created_at: float = field(default_factory=time.time)


class JobScheduler:
    """Manages scheduled engine jobs with cron expressions."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue = JobQueue()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._execution_log: list[dict[str, Any]] = []

    def schedule(
        self,
        engine_name: str,
        schedule: str,
        params: dict[str, Any] | None = None,
        description: str = "",
    ) -> str:
        """Schedule a recurring engine job. Returns job_id."""
        job_id = generate_id("sched")
        job = Job(
            job_id=job_id,
            engine_name=engine_name,
            params=params or {},
            schedule=schedule,
            description=description or f"{engine_name} @ {CronParser.next_run_description(schedule)}",
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info("Scheduled job %s: %s (%s)", job_id, engine_name, schedule)
        return job_id

    def unschedule(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def enable(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.enabled = True
                return True
            return False

    def disable(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.enabled = False
                return True
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "job_id": j.job_id,
                    "engine": j.engine_name,
                    "schedule": j.schedule,
                    "schedule_desc": CronParser.next_run_description(j.schedule),
                    "enabled": j.enabled,
                    "run_count": j.run_count,
                    "error_count": j.error_count,
                    "last_run": j.last_run,
                    "description": j.description,
                }
                for j in self._jobs.values()
            ]

    def check_and_queue(self) -> list[str]:
        """Check all jobs and queue those that should run now."""
        now = datetime.now()
        queued = []
        with self._lock:
            for job in self._jobs.values():
                if not job.enabled:
                    continue
                if job.last_run and (time.time() - job.last_run) < 55:
                    continue  # Don't run more than once per minute
                if CronParser.should_run(job.schedule, now):
                    self._queue.enqueue(job.engine_name, job.params, priority=3)
                    job.last_run = time.time()
                    job.run_count += 1
                    queued.append(job.job_id)
        return queued

    def process_queue(self, orchestrator=None) -> list[dict[str, Any]]:
        """Process queued jobs. Optionally uses orchestrator for execution."""
        results = []
        while self._queue.size() > 0:
            job_data = self._queue.dequeue()
            if job_data is None:
                break

            if orchestrator:
                try:
                    result = orchestrator.submit_task(job_data["engine"], job_data["params"])
                    entry = {"job_id": job_data["job_id"], "engine": job_data["engine"],
                             "status": result.get("status", "unknown"), "timestamp": time.time()}
                except Exception as exc:
                    entry = {"job_id": job_data["job_id"], "engine": job_data["engine"],
                             "status": "error", "error": str(exc), "timestamp": time.time()}
            else:
                entry = {"job_id": job_data["job_id"], "engine": job_data["engine"],
                         "status": "queued_only", "timestamp": time.time()}

            results.append(entry)
            self._execution_log.append(entry)
            if len(self._execution_log) > 5000:
                self._execution_log = self._execution_log[-5000:]

        return results

    def start(self, orchestrator=None, interval: int = 60) -> None:
        """Start scheduler loop in background."""
        if self._running:
            return
        self._running = True

        def loop():
            while self._running:
                try:
                    self.check_and_queue()
                    self.process_queue(orchestrator)
                except Exception as exc:
                    logger.error("Scheduler error: %s", exc)
                time.sleep(interval)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started (interval=%ds)", interval)

    def stop(self) -> None:
        self._running = False

    def get_execution_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._execution_log[-limit:])

    @property
    def queue(self) -> JobQueue:
        return self._queue
