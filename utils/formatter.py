from typing import Any


def format_task_summary(task: dict[str, Any]) -> str:
    status = task.get("status", "unknown")
    task_type = task.get("type", "generic")
    task_id = task.get("id", "?")
    return f"[{status}] {task_type} (id={task_id})"


def format_route_path(route: list[str]) -> str:
    return " -> ".join(route) if route else "(empty route)"
