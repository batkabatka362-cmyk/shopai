"""Coordinator — task decomposition, assignment, and result aggregation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agents.communication.message_bus import MessageBus


class Coordinator:
    """Splits tasks into subtasks, assigns them to agents, and merges results."""

    def __init__(self, message_bus: MessageBus | None = None) -> None:
        self._bus = message_bus or MessageBus()
        # task_id -> {agent_id: subtask_dict}
        self._task_assignments: dict[str, dict[str, dict]] = {}
        # task_id -> {agent_id: result_dict}
        self._results: dict[str, dict[str, dict]] = {}

    @staticmethod
    def _new_task_id() -> str:
        return f"task-{uuid.uuid4().hex[:12]}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def coordinate_task(self, task: dict, agents: list[str]) -> dict:
        """Full coordination cycle: assign subtasks, notify agents, return tracking info."""
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
            "assignments": assignments,
            "agents": agents,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def assign_subtasks(self, task: dict, agents: list[str]) -> dict[str, dict]:
        """Split a task into one subtask per agent (round-robin by steps or equal share)."""
        task_id = task.get("id") or self._new_task_id()
        steps = task.get("steps", [])
        description = task.get("description", "")

        assignments: dict[str, dict] = {}
        if steps:
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

        self._task_assignments[task_id] = assignments
        self._results.setdefault(task_id, {})
        return assignments

    def collect_results(self, task_id: str) -> dict:
        """Gather all submitted results for a task."""
        if task_id not in self._task_assignments:
            raise KeyError(f"Unknown task: {task_id}")

        assignments = self._task_assignments[task_id]
        results = self._results.get(task_id, {})

        # Also check bus for result messages
        self._bus.subscribe(f"result.{task_id}", "coordinator")
        bus_messages = self._bus.get_messages(
            subscriber_id="coordinator",
            topic=f"result.{task_id}",
        )
        for msg in bus_messages:
            aid = msg["payload"].get("agent_id", msg["sender"])
            if aid not in results:
                results[aid] = msg["payload"]

        self._results[task_id] = results

        completed = set(results.keys())
        expected = set(assignments.keys())

        return {
            "task_id": task_id,
            "total_agents": len(expected),
            "completed": len(completed),
            "pending": sorted(expected - completed),
            "results": dict(results),
            "all_complete": completed >= expected,
        }

    def submit_result(self, task_id: str, agent_id: str, result: dict) -> None:
        """Agents call this to submit their subtask result."""
        if task_id not in self._task_assignments:
            raise KeyError(f"Unknown task: {task_id}")
        self._results.setdefault(task_id, {})[agent_id] = dict(result)

        # Also publish to bus
        self._bus.publish(
            topic=f"result.{task_id}",
            message={"agent_id": agent_id, **result},
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
            best = max(
                results,
                key=lambda r: r.get("confidence", r.get("score", 0)),
            )
            return {"merged": True, "data": dict(best), "strategy": "best"}

        raise ValueError(f"Unknown merge strategy: {merge_strategy}")
