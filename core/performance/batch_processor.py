"""BatchProcessor — processes multiple engine tasks efficiently."""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id
from engines.registry import get_engine
from engines.base.engine_types import EngineInput

logger = get_logger("performance.batch")


class BatchProcessor:
    """Processes batches of engine tasks with parallel execution."""

    def __init__(self, max_workers: int = 5) -> None:
        self._max_workers = max_workers

    def process(
        self,
        engine_name: str,
        items: list[dict[str, Any]],
        shared_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process a batch of items through an engine."""
        start = time.monotonic()
        batch_id = generate_id("batch")
        results: list[dict[str, Any]] = [None] * len(items)
        errors = []

        logger.info("Batch %s: %d items for engine '%s'", batch_id, len(items), engine_name)

        # Process in parallel chunks
        semaphore = threading.Semaphore(self._max_workers)
        threads = []

        def worker(idx: int, item: dict[str, Any]):
            semaphore.acquire()
            try:
                data = copy.deepcopy(shared_params or {})
                data.update(item)
                engine = get_engine(engine_name)
                inp = EngineInput(
                    task_id=f"{batch_id}_item{idx}",
                    engine_name=engine_name,
                    data=data,
                )
                output = engine.run(inp)
                results[idx] = {
                    "index": idx,
                    "status": output.status.value,
                    "result": output.result,
                    "error": output.error,
                }
            except Exception as exc:
                results[idx] = {"index": idx, "status": "error", "result": {}, "error": str(exc)}
                errors.append({"index": idx, "error": str(exc)})
            finally:
                semaphore.release()

        for i, item in enumerate(items):
            t = threading.Thread(target=worker, args=(i, item))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=120)

        elapsed = time.monotonic() - start
        completed = sum(1 for r in results if r and r.get("status") == "completed")

        return {
            "batch_id": batch_id,
            "engine": engine_name,
            "total": len(items),
            "completed": completed,
            "failed": len(items) - completed,
            "elapsed_seconds": round(elapsed, 3),
            "avg_per_item": round(elapsed / max(len(items), 1), 3),
            "results": [r for r in results if r],
            "errors": errors,
        }

    def process_multi_engine(
        self,
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Process tasks across multiple engines in parallel.

        Each task: {"engine": str, "data": dict}
        """
        start = time.monotonic()
        batch_id = generate_id("multi")
        results: list[dict[str, Any]] = [None] * len(tasks)
        semaphore = threading.Semaphore(self._max_workers)
        threads = []

        def worker(idx: int, task: dict[str, Any]):
            semaphore.acquire()
            try:
                eng_name = task["engine"]
                data = task.get("data", {})
                engine = get_engine(eng_name)
                inp = EngineInput(task_id=f"{batch_id}_{idx}", engine_name=eng_name, data=data)
                output = engine.run(inp)
                results[idx] = {"index": idx, "engine": eng_name, "status": output.status.value, "result": output.result}
            except Exception as exc:
                results[idx] = {"index": idx, "engine": task.get("engine", "?"), "status": "error", "error": str(exc)}
            finally:
                semaphore.release()

        for i, task in enumerate(tasks):
            t = threading.Thread(target=worker, args=(i, task))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=120)

        elapsed = time.monotonic() - start
        return {
            "batch_id": batch_id,
            "total": len(tasks),
            "completed": sum(1 for r in results if r and r.get("status") == "completed"),
            "elapsed_seconds": round(elapsed, 3),
            "results": [r for r in results if r],
        }
