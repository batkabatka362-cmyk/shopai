"""Environment variable and configuration management."""

import os
from typing import Any, Optional


class EnvManager:
    """Manage environment variables, .env files, and configuration validation."""

    def get(self, key: str, default: Any = None) -> Any:
        """Get an environment variable value."""
        return os.environ.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set an environment variable in the current process."""
        os.environ[key] = str(value)

    def load_env_file(self, filepath: str) -> dict:
        """Parse a .env file (KEY=VALUE format) and load into os.environ.

        Supports:
            - Comments (lines starting with #)
            - Blank lines
            - Quoted values (single or double quotes stripped)
            - Inline comments after values

        Returns:
            Dict of loaded key-value pairs.
        """
        loaded = {}
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                # Remove inline comments (not inside quotes)
                if value and value[0] not in ('"', "'"):
                    comment_idx = value.find("#")
                    if comment_idx > 0:
                        value = value[:comment_idx].strip()

                # Strip surrounding quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]

                os.environ[key] = value
                loaded[key] = value
        return loaded

    def get_all(self, prefix: str = "SHOPAI_") -> dict:
        """Get all environment variables matching a prefix."""
        return {k: v for k, v in os.environ.items() if k.startswith(prefix)}

    def validate_required(self, required_keys: list[str]) -> list[str]:
        """Validate that required environment variables are set.

        Returns:
            List of missing keys (empty if all present).
        """
        return [k for k in required_keys if k not in os.environ]

    def get_environment(self) -> str:
        """Get the current environment name based on SHOPAI_ENV.

        Returns one of: development, staging, production (default: development).
        """
        env = os.environ.get(
            "SHOPAI_ENV", "development",
        ).strip().lower()
        if env in ("production", "prod"):
            return "production"
        if env in ("staging", "stage"):
            return "staging"
        return "development"
