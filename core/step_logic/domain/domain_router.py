"""DomainRouter — routes engine to its domain-specific logic.

Maps engine names to the right business logic module.
Falls back to generic SmartExecutor if no domain match.
"""
from __future__ import annotations
from typing import Any

from .pricing_logic import PricingLogic
from .marketing_logic import MarketingLogic
from .inventory_logic import InventoryLogic
from .seo_logic import SeoLogic
from .customer_logic import CustomerLogic


class DomainRouter:
    """Routes engines to domain-specific computation logic."""

    def __init__(self) -> None:
        self._domains = [
            PricingLogic(),
            MarketingLogic(),
            InventoryLogic(),
            SeoLogic(),
            CustomerLogic(),
        ]

    def get_domain(self, engine_name: str):
        """Get domain logic for an engine. Returns None if no match."""
        for domain in self._domains:
            if domain.applies_to(engine_name):
                return domain
        return None

    def analyze(self, engine_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Run domain-specific analysis. Returns None if no domain match."""
        domain = self.get_domain(engine_name)
        if domain is None:
            return None
        return domain.analyze(data)

    def execute(self, engine_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Run domain-specific execution. Returns None if no domain match."""
        domain = self.get_domain(engine_name)
        if domain is None:
            return None
        return domain.execute(data)

    def covers(self, engine_name: str) -> bool:
        """Check if any domain covers this engine."""
        return any(d.applies_to(engine_name) for d in self._domains)

    def list_covered_engines(self) -> dict[str, list[str]]:
        """List all engines covered by each domain."""
        result = {}
        for domain in self._domains:
            name = type(domain).__name__
            engines = sorted(domain.__class__.__dict__.get(
                f"{name.upper().replace('LOGIC','')}_ENGINES",
                getattr(domain, [a for a in dir(domain) if a.endswith('_ENGINES')][0], set())
                if [a for a in dir(domain) if a.endswith('_ENGINES')] else set()
            ))
            result[name] = engines
        return result
