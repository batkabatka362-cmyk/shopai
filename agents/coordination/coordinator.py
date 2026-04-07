"""Coordinator — task decomposition, assignment, and result aggregation."""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone

from agents.communication.message_bus import MessageBus
from utils.helpers import safe_float


class Coordinator:
    """Splits tasks into subtasks, assigns them to agents, and merges results.

    Thread-safe: a single internal lock guards both _task_assignments
    and _results so concurrent submit_result / collect_results /
    coordinate_task calls can't observe partial state.
    """

    def __init__(self, message_bus: MessageBus | None = None) -> None:
        self._bus = message_bus or MessageBus()
        # task_id -> {agent_id: subtask_dict}
        self._task_assignments: dict[str, dict[str, dict]] = {}
        # task_id -> {agent_id: result_dict}
        self._results: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()
        # Subscribe ONCE to result.* topics (the previous version
        # subscribed inside collect_results on every call, which
        # accumulated subscription objects in the bus over time).
        # We use a wildcard-style sentinel here: the bus stores all
        # messages so collect_results can still pull them via a
        # one-shot lazy subscribe per task_id, dedup'd via this set.
        self._subscribed_tasks: set[str] = set()

    @staticmethod
    def _new_task_id() -> str:
        return f"task-{uuid.uuid4().hex[:12]}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def coordinate_task(self, task: dict, agents: list[str]) -> dict:
        """Full coordination cycle: assign subtasks, notify agents, return tracking info."""
        if not isinstance(task, dict):
            task = {}
        if not isinstance(agents, list) or not agents:
            return {
                "task_id": "",
                "status": "rejected",
                "error": "agents list must be non-empty",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        task_id = task.get("id") or self._new_task_id()
        task_with_id = {**task, "id": task_id}

        assignments = self.assign_subtasks(task_with_id, agents)

        # Publish subtask assignments to the bus so agents can pick them up
        for agent_id, subtask in assignments.items():
            self._bus.publish(
                topic=f"task.{task_id}",
                message={"subtask": subtask, "assigned_to": agent_id},
                sender="coordinator",
            )

        return {
            "task_id": task_id,
            "status": "dispatched",
            "assignments": copy.deepcopy(assignments),
            "agents": list(agents),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def assign_subtasks(self, task: dict, agents: list[str]) -> dict[str, dict]:
        """Split a task into one subtask per agent (round-robin by steps or equal share).

        Defensive: empty agents list is rejected with ValueError
        instead of crashing the round-robin distribution with
        ZeroDivisionError on `idx % len(agents)`.
        """
        if not isinstance(agents, list) or not agents:
            raise ValueError("assign_subtasks requires a non-empty agents list")
        if not isinstance(task, dict):
            task = {}
        task_id = task.get("id") or self._new_task_id()
        steps = task.get("steps") or []
        description = task.get("description", "")

        assignments: dict[str, dict] = {}
        if isinstance(steps, list) and steps:
            # Distribute steps across agents
            for idx, step in enumerate(steps):
                agent_id = agents[idx % len(agents)]
                subtask = assignments.setdefault(agent_id, {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "steps": [],
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                subtask["steps"].append(step)
        else:
            # No explicit steps — give each agent the full description
            for agent_id in agents:
                assignments[agent_id] = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "description": description,
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

        with self._lock:
            self._task_assignments[task_id] = assignments
            self._results.setdefault(task_id, {})
        return assignments

    def collect_results(self, task_id: str) -> dict:
        """Gather all submitted results for a task."""
        with self._lock:
            if task_id not in self._task_assignments:
                raise KeyError(f"Unknown task: {task_id}")
            assignments = self._task_assignments[task_id]
            results = dict(self._results.get(task_id, {}))
            already_subscribed = task_id in self._subscribed_tasks

        # Subscribe to the bus topic the first time we collect for
        # this task. The bus stores all prior messages so a late
        # subscribe still picks them up via get_messages.
        if not already_subscribed:
            self._bus.subscribe(f"result.{task_id}", "coordinator")
            with self._lock:
                self._subscribed_tasks.add(task_id)

        bus_messages = self._bus.get_messages(
            subscriber_id="coordinator",
            topic=f"result.{task_id}",
        )
        for msg in bus_messages:
            payload = msg.get("payload") if isinstance(msg, dict) else None
            if not isinstance(payload, dict):
                continue
            aid = payload.get("agent_id") or msg.get("sender", "unknown")
            if aid not in results:
                results[aid] = copy.deepcopy(payload)

        with self._lock:
            self._results[task_id] = results
            results_snapshot = copy.deepcopy(results)

        completed = set(results_snapshot.keys())
        expected = set(assignments.keys())

        return {
            "task_id": task_id,
            "total_agents": len(expected),
            "completed": len(completed),
            "pending": sorted(expected - completed),
            "results": results_snapshot,
            "all_complete": completed >= expected,
        }

    def submit_result(self, task_id: str, agent_id: str, result: dict) -> None:
        """Agents call this to submit their subtask result.

        Defensive: non-dict results are wrapped as {"raw": ...}
        instead of crashing dict(result). The stored result is a
        deep copy so the agent mutating its own dict after submit
        can't bleed into the coordinator's view.
        """
        with self._lock:
            if task_id not in self._task_assignments:
                raise KeyError(f"Unknown task: {task_id}")
            payload = (
                copy.deepcopy(result) if isinstance(result, dict)
                else {"raw": str(result)[:500]}
            )
            self._results.setdefault(task_id, {})[agent_id] = payload

        # Also publish to bus (outside the lock — bus has its own lock)
        self._bus.publish(
            topic=f"result.{task_id}",
            message={"agent_id": agent_id, **payload},
            sender=agent_id,
        )

    def merge_results(
        self, results: list[dict], merge_strategy: str = "combine"
    ) -> dict:
        """Merge a list of result dicts into a single result.

        Strategies:
        - combine: merge all key-value pairs (later results override conflicts)
        - append: collect values into lists keyed by field name
        - best: pick the result with the highest 'confidence' or 'score' field
        """
        if not results:
            return {"merged": True, "data": {}, "strategy": merge_strategy}
        # Filter to dict-shaped entries so a malformed list doesn't
        # crash on .items() / .get() below.
        results = [r for r in results if isinstance(r, dict)]
        if not results:
            return {"merged": True, "data": {}, "strategy": merge_strategy}

        if merge_strategy == "combine":
            merged: dict = {}
            for r in results:
                merged.update(r)
            return {"merged": True, "data": merged, "strategy": "combine"}

        if merge_strategy == "append":
            merged_lists: dict[str, list] = {}
            for r in results:
                for k, v in r.items():
                    merged_lists.setdefault(k, []).append(v)
            return {"merged": True, "data": merged_lists, "strategy": "append"}

        if merge_strategy == "best":
            # Use safe_float so a present-but-None confidence/score
            # doesn't crash max() on a None comparison.
            def _score(r: dict) -> float:
                conf = r.get("confidence")
                if conf is not None:
                    return safe_float(conf)
                return safe_float(r.get("score"))
            best = max(results, key=_score)
            return {"merged": True, "data": dict(best), "strategy": "best"}

        raise ValueError(f"Unknown merge strategy: {merge_strategy}")
