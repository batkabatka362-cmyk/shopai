"""Container lifecycle management."""

import uuid
import time
from datetime import datetime, timezone
from typing import Optional


class ContainerManager:
    """Manage container creation, lifecycle, and log retrieval."""

    VALID_STATUSES = ("created", "running", "stopped", "restarting", "removed")

    def __init__(self):
        self._containers: dict[str, dict] = {}

    def create_container(self, name: str, image: str, config: Optional[dict] = None) -> dict:
        """Create a new container.

        Args:
            name: Human-readable container name.
            image: Container image identifier.
            config: Optional dict with ports, env, volumes, etc.

        Returns:
            Container info dict.
        """
        container_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        container = {
            "container_id": container_id,
            "name": name,
            "image": image,
            "config": config or {},
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "stopped_at": None,
            "logs": [],
        }
        self._containers[container_id] = container
        self._add_log(container_id, f"Container '{name}' created with image '{image}'")
        return self._public_info(container)

    def start(self, container_id: str) -> dict:
        """Start a container."""
        container = self._get_or_raise(container_id)
        if container["status"] == "running":
            return {"status": "already_running", "container_id": container_id}

        now = datetime.now(timezone.utc).isoformat()
        container["status"] = "running"
        container["started_at"] = now
        container["updated_at"] = now
        self._add_log(container_id, "Container started")
        return self._public_info(container)

    def stop(self, container_id: str) -> dict:
        """Stop a running container."""
        container = self._get_or_raise(container_id)
        if container["status"] == "stopped":
            return {"status": "already_stopped", "container_id": container_id}

        now = datetime.now(timezone.utc).isoformat()
        container["status"] = "stopped"
        container["stopped_at"] = now
        container["updated_at"] = now
        self._add_log(container_id, "Container stopped")
        return self._public_info(container)

    def restart(self, container_id: str) -> dict:
        """Restart a container (stop + start)."""
        container = self._get_or_raise(container_id)
        now = datetime.now(timezone.utc).isoformat()
        container["status"] = "running"
        container["started_at"] = now
        container["updated_at"] = now
        self._add_log(container_id, "Container restarted")
        return self._public_info(container)

    def list_containers(self, status: Optional[str] = None) -> list[dict]:
        """List all containers, optionally filtered by status."""
        containers = list(self._containers.values())
        if status:
            containers = [c for c in containers if c["status"] == status]
        return [self._public_info(c) for c in containers]

    def get_logs(self, container_id: str, lines: int = 100) -> list[str]:
        """Get recent log lines for a container."""
        container = self._get_or_raise(container_id)
        return container["logs"][-lines:]

    def remove(self, container_id: str) -> bool:
        """Remove a container. Must be stopped first.

        Returns True if successfully removed.
        """
        container = self._get_or_raise(container_id)
        if container["status"] == "running":
            # Stop it first
            container["status"] = "stopped"
            container["stopped_at"] = datetime.now(timezone.utc).isoformat()
            self._add_log(container_id, "Container stopped for removal")

        self._add_log(container_id, "Container removed")
        del self._containers[container_id]
        return True

    def _get_or_raise(self, container_id: str) -> dict:
        if container_id not in self._containers:
            raise KeyError(f"Container '{container_id}' not found")
        return self._containers[container_id]

    def _add_log(self, container_id: str, message: str) -> None:
        if container_id in self._containers:
            timestamp = datetime.now(timezone.utc).isoformat()
            self._containers[container_id]["logs"].append(f"[{timestamp}] {message}")

    @staticmethod
    def _public_info(container: dict) -> dict:
        """Return container info without internal logs."""
        return {
            "container_id": container["container_id"],
            "name": container["name"],
            "image": container["image"],
            "status": container["status"],
            "created_at": container["created_at"],
            "started_at": container["started_at"],
            "stopped_at": container["stopped_at"],
        }
