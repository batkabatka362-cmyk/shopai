"""ContentScheduler — schedules content jobs for future publication.

Jobs are persisted to ``/tmp/shopai_scheduler.json`` so they survive
process restarts.  Uses only the Python standard library.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

_JOBS_PATH = "/tmp/shopai_scheduler.json"
_lock = threading.Lock()


class ContentScheduler:
    """Schedule, cancel, and list content publication jobs."""

    def __init__(self, jobs_path: str = _JOBS_PATH) -> None:
        self._jobs_path = jobs_path
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load_jobs()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def schedule(
        self,
        content_id: str,
        publish_at: str,
        platform: str,
        job_config: dict[str, Any],
    ) -> str:
        """Register a new publication job.

        Args:
            content_id:  Caller-supplied content identifier (used as a tag,
                         not necessarily unique).
            publish_at:  ISO-8601 UTC datetime string, e.g.
                         ``"2024-06-01T09:00:00Z"``.
            platform:    Target platform (``"shopify"``, ``"facebook"``, …).
            job_config:  Arbitrary config stored alongside the job.

        Returns:
            Unique ``job_id`` string (UUID4).
        """
        job_id = str(uuid.uuid4())
        job: dict[str, Any] = {
            "job_id": job_id,
            "content_id": content_id,
            "publish_at": publish_at,
            "platform": platform,
            "job_config": job_config,
            "status": "scheduled",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cancelled_at": None,
            "executed_at": None,
        }
        with _lock:
            self._jobs[job_id] = job
            self._persist_jobs()
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job.

        Returns:
            ``True`` if the job existed and was cancelled; ``False`` if the
            job_id was not found or the job was already cancelled/executed.
        """
        with _lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "scheduled":
                return False
            job["status"] = "cancelled"
            job["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            self._persist_jobs()
        return True

    def list_scheduled(self, platform: str | None = None) -> list[dict[str, Any]]:
        """Return all jobs with status ``"scheduled"``.

        Args:
            platform: Optional filter; if given only jobs for that platform
                      are returned.

        Returns:
            List of job dicts sorted by ``publish_at`` ascending.
        """
        with _lock:
            jobs = [
                j for j in self._jobs.values()
                if j["status"] == "scheduled"
                and (platform is None or j["platform"] == platform)
            ]
        return sorted(jobs, key=lambda j: j.get("publish_at", ""))

    def get_due_jobs(self, now: str | None = None) -> list[dict[str, Any]]:
        """Return all scheduled jobs whose ``publish_at`` is <= *now*.

        Args:
            now: ISO-8601 datetime string to use as the reference time.
                 Defaults to the current UTC time.

        Returns:
            List of job dicts sorted by ``publish_at`` ascending.
        """
        if now is None:
            reference = datetime.now(timezone.utc)
        else:
            reference = _parse_iso(now)

        with _lock:
            due = [
                j for j in self._jobs.values()
                if j["status"] == "scheduled"
                and _parse_iso(j["publish_at"]) <= reference
            ]
        return sorted(due, key=lambda j: j.get("publish_at", ""))

    def mark_executed(self, job_id: str) -> bool:
        """Mark a job as executed (called by the publishing layer)."""
        with _lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job["status"] = "executed"
            job["executed_at"] = datetime.now(timezone.utc).isoformat()
            self._persist_jobs()
        return True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve a single job by ID."""
        with _lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _persist_jobs(self) -> None:
        """Write the current jobs dict to the JSON file (caller holds lock)."""
        try:
            tmp_path = self._jobs_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._jobs, fh, indent=2)
            os.replace(tmp_path, self._jobs_path)
        except OSError:
            # Non-fatal: in-memory jobs are still valid
            pass

    def _load_jobs(self) -> None:
        """Read jobs from the JSON file if it exists."""
        try:
            if os.path.exists(self._jobs_path):
                with open(self._jobs_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    self._jobs = data
        except (OSError, json.JSONDecodeError):
            self._jobs = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(dt_str: str) -> datetime:
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    dt_str = dt_str.strip()
    # Python 3.7+ fromisoformat doesn't handle 'Z' suffix
    dt_str = dt_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(dt_str)
    except ValueError:
        # Fallback: try stripping timezone and assume UTC
        dt = datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
