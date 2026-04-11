"""Config schema + validation for ShopAI.

Central registry of every environment variable the application reads,
plus a validator that produces actionable error and warning messages.

Three problems this solves:

1. Silent failure when `.env` is missing — the app used to start fine and
   fail at the first Shopify call. Now `validate_config()` surfaces it.
2. No type safety on scalar values — e.g. SHOPAI_LOG_MAX_MB="abc" would
   previously silently fall back to the default.
3. No way to list / discover configuration — `shopai config show` prints
   the full schema with current values, defaults, and sources.

Usage:
    from infrastructure.config.schema import validate_config, get_config_report

    issues = validate_config()
    if issues.errors:
        for err in issues.errors:
            print(f"ERROR: {err}")
        sys.exit(1)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional


# --- Schema definitions ----------------------------------------------------

FieldType = Literal["str", "int", "float", "bool", "choice", "path", "url"]


@dataclass
class ConfigField:
    """A single environment variable's schema entry."""

    name: str
    type: FieldType
    description: str
    default: Any = None
    required: bool = False
    choices: list[str] = field(default_factory=list)
    secret: bool = False  # masked in `config show`
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    validator: Optional[Callable[[str], Optional[str]]] = None

    def current_value(self) -> Optional[str]:
        return os.environ.get(self.name)

    def is_set(self) -> bool:
        return self.name in os.environ and os.environ[self.name] != ""

    def effective(self) -> Any:
        """Return the effective (parsed) value, using default if unset."""
        raw = self.current_value()
        if raw is None or raw == "":
            return self.default
        try:
            return self._parse(raw)
        except Exception:  # noqa: BLE001
            return self.default

    def _parse(self, raw: str) -> Any:
        if self.type == "int":
            return int(raw)
        if self.type == "float":
            return float(raw)
        if self.type == "bool":
            return raw.lower() in ("1", "true", "yes", "on")
        return raw

    def display(self) -> str:
        """Stringified effective value, masked if secret."""
        val = self.effective()
        if val is None:
            return "<unset>"
        s = str(val)
        if self.secret and s:
            return s[:4] + "..." if len(s) > 4 else "***"
        return s


# --- The full schema -------------------------------------------------------
#
# Adding a new env var? Add a ConfigField here so it's discoverable via
# `shopai config show` and validated at startup.

SCHEMA: list[ConfigField] = [
    # ── Environment ─────────────────────────────────────────────
    ConfigField(
        name="SHOPAI_ENV",
        type="choice",
        description="Deployment environment",
        default="development",
        choices=["development", "staging", "production", "dev", "stage", "prod"],
    ),
    ConfigField(
        name="SHOPAI_DATA_DIR",
        type="path",
        description="Directory for SQLite databases and caches",
        default=None,  # computed relative to repo root if unset
    ),

    # ── Shopify credentials ─────────────────────────────────────
    ConfigField(
        name="SHOPAI_SHOPIFY_URL",
        type="str",
        description="Shopify store URL (e.g. mystore.myshopify.com)",
    ),
    ConfigField(
        name="SHOPAI_SHOPIFY_KEY",
        type="str",
        description="Legacy static admin API token (pre-2026 custom apps)",
        secret=True,
    ),
    ConfigField(
        name="SHOPAI_SHOPIFY_CLIENT_ID",
        type="str",
        description="OAuth client ID (2026+ custom apps)",
        secret=True,
    ),
    ConfigField(
        name="SHOPAI_SHOPIFY_CLIENT_SECRET",
        type="str",
        description="OAuth client secret (2026+ custom apps)",
        secret=True,
    ),

    # ── Logging ─────────────────────────────────────────────────
    ConfigField(
        name="SHOPAI_LOG_LEVEL",
        type="choice",
        description="Minimum log level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    ),
    ConfigField(
        name="SHOPAI_LOG_FORMAT",
        type="choice",
        description="Log format",
        default="text",
        choices=["text", "json"],
    ),
    ConfigField(
        name="SHOPAI_LOG_FILE",
        type="path",
        description="Log file path (enables rotation). Empty = stdout only",
        default="",
    ),
    ConfigField(
        name="SHOPAI_LOG_MAX_MB",
        type="float",
        description="Rotate log file when it exceeds this size (MB)",
        default=10,
        min_value=0.001,
        max_value=10000,
    ),
    ConfigField(
        name="SHOPAI_LOG_BACKUPS",
        type="int",
        description="Number of rotated log files to keep",
        default=5,
        min_value=0,
        max_value=100,
    ),

    # ── LLM / AI ────────────────────────────────────────────────
    ConfigField(
        name="SHOPAI_OLLAMA_URL",
        type="url",
        description="Base URL for the local Ollama server",
        default="http://localhost:11434",
    ),

    # ── Integrations ────────────────────────────────────────────
    ConfigField(
        name="SHOPAI_TELEGRAM_TOKEN",
        type="str",
        description="Telegram bot token for notifications",
        secret=True,
    ),
    ConfigField(
        name="SHOPAI_API_TOKEN",
        type="str",
        description="Master token for the webhook / dashboard API",
        secret=True,
    ),
]


# --- Validation ------------------------------------------------------------

@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok()


def _validate_field(f: ConfigField) -> list[str]:
    """Return a list of error messages for a single field (may be empty)."""
    errors: list[str] = []
    raw = f.current_value()

    if raw is None or raw == "":
        if f.required:
            errors.append(
                f"{f.name} is required but not set ({f.description})"
            )
        return errors

    # Type parse
    if f.type == "int":
        try:
            val = int(raw)
        except ValueError:
            errors.append(f"{f.name}={raw!r} is not a valid integer")
            return errors
        if f.min_value is not None and val < f.min_value:
            errors.append(f"{f.name}={val} is below minimum {f.min_value}")
        if f.max_value is not None and val > f.max_value:
            errors.append(f"{f.name}={val} is above maximum {f.max_value}")

    elif f.type == "float":
        try:
            val = float(raw)
        except ValueError:
            errors.append(f"{f.name}={raw!r} is not a valid number")
            return errors
        if f.min_value is not None and val < f.min_value:
            errors.append(f"{f.name}={val} is below minimum {f.min_value}")
        if f.max_value is not None and val > f.max_value:
            errors.append(f"{f.name}={val} is above maximum {f.max_value}")

    elif f.type == "bool":
        if raw.lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
            errors.append(f"{f.name}={raw!r} is not a valid boolean")

    elif f.type == "choice":
        # Choice comparison — case-insensitive for environments / log levels
        normalized = raw.lower() if f.name.endswith(("_LEVEL", "_FORMAT", "_ENV")) else raw
        choices_norm = [c.lower() if f.name.endswith(("_LEVEL", "_FORMAT", "_ENV")) else c
                        for c in f.choices]
        if normalized not in choices_norm:
            errors.append(
                f"{f.name}={raw!r} not in allowed values: {', '.join(f.choices)}"
            )

    elif f.type == "url":
        if not (raw.startswith("http://") or raw.startswith("https://")):
            errors.append(
                f"{f.name}={raw!r} is not a valid URL (must start with http:// or https://)"
            )

    elif f.type == "path":
        # Path existence is only checked for LOG_FILE's parent, since
        # other paths may legitimately be created at startup.
        pass

    if f.validator:
        err = f.validator(raw)
        if err:
            errors.append(f"{f.name}: {err}")

    return errors


def validate_config(schema: Optional[list[ConfigField]] = None) -> ValidationResult:
    """Validate every env var against the schema + cross-field constraints."""
    schema = schema or SCHEMA
    result = ValidationResult()

    for f in schema:
        result.errors.extend(_validate_field(f))

    # Cross-field: Shopify auth requires URL + at least one credential path
    url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
    legacy = os.environ.get("SHOPAI_SHOPIFY_KEY", "")
    cid = os.environ.get("SHOPAI_SHOPIFY_CLIENT_ID", "")
    csec = os.environ.get("SHOPAI_SHOPIFY_CLIENT_SECRET", "")

    if url and not (legacy or (cid and csec)):
        result.warnings.append(
            "SHOPAI_SHOPIFY_URL is set but no credentials are configured — "
            "provide either SHOPAI_SHOPIFY_KEY (legacy) or both "
            "SHOPAI_SHOPIFY_CLIENT_ID and SHOPAI_SHOPIFY_CLIENT_SECRET (OAuth)"
        )
    if (cid and not csec) or (csec and not cid):
        result.errors.append(
            "SHOPAI_SHOPIFY_CLIENT_ID and SHOPAI_SHOPIFY_CLIENT_SECRET must "
            "both be set together for OAuth"
        )
    if not url and (legacy or cid or csec):
        result.errors.append(
            "Shopify credentials are set but SHOPAI_SHOPIFY_URL is missing"
        )

    # Log file: if set, parent directory must be writable
    log_file = os.environ.get("SHOPAI_LOG_FILE", "").strip()
    if log_file:
        parent = Path(log_file).parent
        if parent.exists() and not os.access(parent, os.W_OK):
            result.errors.append(
                f"SHOPAI_LOG_FILE={log_file!r}: parent directory is not writable"
            )

    # Production warnings
    env = os.environ.get("SHOPAI_ENV", "development").lower()
    if env in ("production", "prod"):
        log_level = os.environ.get("SHOPAI_LOG_LEVEL", "WARNING").upper()
        if log_level == "DEBUG":
            result.warnings.append(
                "SHOPAI_ENV=production with SHOPAI_LOG_LEVEL=DEBUG will emit "
                "verbose logs — consider INFO or WARNING"
            )
        if not os.environ.get("SHOPAI_API_TOKEN"):
            result.warnings.append(
                "SHOPAI_ENV=production without SHOPAI_API_TOKEN — the "
                "webhook / dashboard API will accept unauthenticated requests"
            )

    return result


def get_config_report(schema: Optional[list[ConfigField]] = None) -> list[dict[str, Any]]:
    """Return a list of rows for `shopai config show`."""
    schema = schema or SCHEMA
    rows = []
    for f in schema:
        rows.append({
            "name": f.name,
            "type": f.type,
            "required": f.required,
            "set": f.is_set(),
            "value": f.display(),
            "default": f.default,
            "description": f.description,
        })
    return rows


def check_env_file(env_path: Optional[str] = None) -> Optional[str]:
    """Return a warning message if a .env file was expected but missing.

    Used by `shopai config check` to surface the "no .env file" case that
    silently used to leave the app unconfigured.
    """
    if env_path is None:
        # Default location: repo root next to cli.py
        from infrastructure.config.env_manager import EnvManager  # noqa: F401
        repo_root = Path(__file__).resolve().parents[2]
        env_path = str(repo_root / ".env")

    if not os.path.exists(env_path):
        return (
            f".env file not found at {env_path} — configuration must come "
            "entirely from environment variables"
        )
    return None
