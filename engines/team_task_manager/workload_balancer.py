"""Team Task Manager Engine — workload balancer.

Balances tasks across team members based on current workload,
capacity, and skill matching.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Workload thresholds (minutes per day)
# ---------------------------------------------------------------------------

_DEFAULT_DAILY_CAPACITY = 480   # 8 hours
_OVERLOAD_THRESHOLD = 0.85      # 85% capacity = overloaded


def balance_workload(
    tasks: list[dict[str, Any]],
    team_members: list[dict[str, Any]],
    current_workload: dict[str, int],
) -> dict[str, Any]:
    """Balance tasks across team members.

    Assigns tasks to the team member with the most available capacity
    who can handle the task category. Tracks workload distribution.

    Args:
        tasks: Generated tasks from task_generator.
        team_members: List of member dicts with id, name, skills, capacity_minutes.
        current_workload: Map of member_id -> currently assigned minutes.

    Returns:
        Structured dict with assigned tasks and workload distribution.
    """
    try:
        task_list = copy.deepcopy(tasks)
        members = copy.deepcopy(team_members)
        workload = copy.deepcopy(current_workload)

        if not members:
            return {
                "status": "success",
                "assigned_tasks": task_list,
                "workload_distribution": {},
                "unassigned_count": len(task_list),
            }

        # Build member capacity map
        member_map: dict[str, dict[str, Any]] = {}
        for m in members:
            mid = str(m.get("id", ""))
            capacity = int(m.get("capacity_minutes", _DEFAULT_DAILY_CAPACITY))
            skills = list(m.get("skills", []))
            current = int(workload.get(mid, 0))
            member_map[mid] = {
                "name": str(m.get("name", "")),
                "capacity": capacity,
                "current_load": current,
                "remaining": capacity - current,
                "skills": skills,
            }

        assigned_tasks: list[dict[str, Any]] = []
        unassigned = 0

        for task in task_list:
            category = str(task.get("category", "general"))
            est_minutes = int(task.get("estimated_minutes", 30))

            # Find best assignee: most remaining capacity with matching skill
            best_id = None
            best_remaining = -1

            for mid, info in member_map.items():
                # Skill match: member skills contain category, or "general" in skills
                skills = info["skills"]
                skill_match = (
                    category in skills
                    or "general" in skills
                    or not skills  # empty skills = can do anything
                )
                if not skill_match:
                    continue

                if info["remaining"] >= est_minutes and info["remaining"] > best_remaining:
                    best_id = mid
                    best_remaining = info["remaining"]

            if best_id is not None:
                task["assignee"] = best_id
                task["assignee_name"] = member_map[best_id]["name"]
                member_map[best_id]["current_load"] += est_minutes
                member_map[best_id]["remaining"] -= est_minutes
            else:
                # Assign to least loaded member regardless of capacity
                least_loaded = min(
                    member_map.items(),
                    key=lambda x: x[1]["current_load"],
                )
                task["assignee"] = least_loaded[0]
                task["assignee_name"] = least_loaded[1]["name"]
                least_loaded[1]["current_load"] += est_minutes
                least_loaded[1]["remaining"] -= est_minutes
                unassigned += 1  # counts as overload assignment

            assigned_tasks.append(task)

        # Build workload distribution
        distribution: dict[str, dict[str, Any]] = {}
        for mid, info in member_map.items():
            utilization = (
                round(info["current_load"] / info["capacity"], 4)
                if info["capacity"] > 0 else 0.0
            )
            distribution[mid] = {
                "name": info["name"],
                "current_load_minutes": info["current_load"],
                "capacity_minutes": info["capacity"],
                "remaining_minutes": info["remaining"],
                "utilization": utilization,
                "overloaded": utilization > _OVERLOAD_THRESHOLD,
            }

        return {
            "status": "success",
            "assigned_tasks": assigned_tasks,
            "workload_distribution": distribution,
            "unassigned_count": unassigned,
        }
    except Exception as exc:
        return {
            "status": "error",
            "assigned_tasks": [],
            "workload_distribution": {},
            "error": f"Workload balancing failed: {exc}",
        }
