"""Base classes for the tools layer.

Defines the adapter ABC that every tool integration must implement,
plus shared data classes for results, metadata, rate configuration,
and health status.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolMetadata:
    """Metadata attached to every tool execution result."""

    duration_ms: float = 0.0
    attempt_count: int = 1
    rate_limited: bool = False
    cost_usd: float = 0.0
    tool_name: str = ""
    action: str = ""


@dataclass
class ToolResult:
    """Standardised result returned by every tool adapter."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: ToolMetadata | None = None


@dataclass
class RateConfig:
    """Per-tool rate-limiting configuration."""

    requests_per_second: float = 2.0
    burst: int = 5
    daily_quota: int | None = None


@dataclass
class HealthStatus:
    """Result of a health-check probe against a tool backend."""

    healthy: bool
    latency_ms: float = 0.0
    last_check: str = ""
    error: str | None = None


class BaseToolAdapter(ABC):
    """Abstract base for every external-service adapter.

    Sub-classes must set the three class-level attributes and implement
    the three abstract methods.  ``configure`` and ``get_rate_config``
    have sensible defaults that adapters may override.
    """

    tool_name: str = ""
    tool_category: str = ""
    version: str = "0.1.0"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def capabilities(self) -> list[str]:
        """Return the list of action names this adapter supports.

        Example: ["product.search", "product.create", "product.update"]
        """

    @abstractmethod
    def execute(self, action: str, params: dict[str, Any]) -> ToolResult:
        """Execute *action* with *params* and return a ``ToolResult``."""

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Probe the backing service and return a ``HealthStatus``."""

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    def configure(self, credentials: dict[str, Any]) -> None:
        """Apply credentials / configuration.

        The default implementation stores every key as an instance attribute
        so simple adapters don't need to override.
        """
        for key, value in credentials.items():
            setattr(self, f"_cred_{key}", value)

    def get_rate_config(self) -> RateConfig:
        """Return the recommended rate-limit settings for this tool."""
        return RateConfig()

    # ------------------------------------------------------------------
    # Helpers available to all adapters
    # ------------------------------------------------------------------

    def _make_result(
        self,
        success: bool,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        *,
        action: str = "",
        duration_ms: float = 0.0,
        attempt_count: int = 1,
        rate_limited: bool = False,
        cost_usd: float = 0.0,
    ) -> ToolResult:
        """Convenience factory used by concrete adapters."""
        meta = ToolMetadata(
            duration_ms=duration_ms,
            attempt_count=attempt_count,
            rate_limited=rate_limited,
            cost_usd=cost_usd,
            tool_name=self.tool_name,
            action=action,
        )
        return ToolResult(success=success, data=data or {}, error=error, metadata=meta)

    def _timed_health_check(self, probe: callable) -> HealthStatus:
        """Run *probe* (a zero-arg callable) and wrap timing / errors."""
        start = time.monotonic()
        try:
            probe()
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                healthy=True,
                latency_ms=round(latency, 1),
                last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=round(latency, 1),
                last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                error=str(exc),
            )
