"""Deployment management with rollback and status tracking."""

import uuid
import time
from datetime import datetime, timezone
from typing import Optional


class Deployer:
    """Manage deployments with validation, status tracking, and rollback support."""

    REQUIRED_CONFIG_KEYS = ["name", "version", "environment"]

    def __init__(self):
        self._deployments: dict[str, dict] = {}

    def deploy(self, config: dict) -> dict:
        """Execute a deployment with the given configuration.

        Args:
            config: Must contain at least: name, version, environment.

        Returns:
            Dict with deployment_id, status, and timestamp.
        """
        errors = self._validate_config(config)
        if errors:
            return {
                "deployment_id": None,
                "status": "failed",
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        deployment_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        deployment = {
            "deployment_id": deployment_id,
            "config": dict(config),
            "status": "deployed",
            "status_history": [
                {"status": "pending", "timestamp": now},
                {"status": "deploying", "timestamp": now},
                {"status": "deployed", "timestamp": now},
            ],
            "created_at": now,
            "updated_at": now,
        }
        self._deployments[deployment_id] = deployment

        return {
            "deployment_id": deployment_id,
            "status": "deployed",
            "timestamp": now,
        }

    def rollback(self, deployment_id: str) -> dict:
        """Roll back a deployment.

        Returns:
            Dict with status and rollback info.
        """
        if deployment_id not in self._deployments:
            return {"status": "error", "message": f"Deployment '{deployment_id}' not found"}

        deployment = self._deployments[deployment_id]
        now = datetime.now(timezone.utc).isoformat()

        if deployment["status"] == "rolled_back":
            return {"status": "error", "message": "Already rolled back"}

        previous_status = deployment["status"]
        deployment["status"] = "rolled_back"
        deployment["status_history"].append({"status": "rolled_back", "timestamp": now})
        deployment["updated_at"] = now

        return {
            "deployment_id": deployment_id,
            "status": "rolled_back",
            "timestamp": now,
            "previous_status": previous_status,
        }

    def get_status(self, deployment_id: str) -> dict:
        """Get current status of a deployment."""
        if deployment_id not in self._deployments:
            return {"status": "not_found", "deployment_id": deployment_id}
        dep = self._deployments[deployment_id]
        return {
            "deployment_id": deployment_id,
            "status": dep["status"],
            "config": dep["config"],
            "created_at": dep["created_at"],
            "updated_at": dep["updated_at"],
            "status_history": dep["status_history"],
        }

    def list_deployments(self, limit: int = 10) -> list[dict]:
        """List recent deployments, most recent first."""
        all_deps = sorted(
            self._deployments.values(),
            key=lambda d: d["created_at"],
            reverse=True,
        )
        return [
            {
                "deployment_id": d["deployment_id"],
                "name": d["config"].get("name"),
                "version": d["config"].get("version"),
                "environment": d["config"].get("environment"),
                "status": d["status"],
                "created_at": d["created_at"],
            }
            for d in all_deps[:limit]
        ]

    def _validate_config(self, config: dict) -> list[str]:
        """Validate deployment config. Returns list of error strings."""
        errors = []
        for key in self.REQUIRED_CONFIG_KEYS:
            if key not in config:
                errors.append(f"Missing required field: {key}")
            elif not config[key]:
                errors.append(f"Empty required field: {key}")

        env = config.get("environment", "")
        valid_envs = ("development", "staging", "production")
        if env and env not in valid_envs:
            errors.append(f"Invalid environment '{env}'. Must be one of: {valid_envs}")

        return errors
