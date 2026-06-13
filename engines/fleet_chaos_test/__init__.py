"""Fleet Chaos Test Engine — W963-34.

Lightweight chaos test. Simulates substrate failures and
verifies the empire keeps running. The final piece of the
7-engine Empire-AGI plan: Q4 (ecosystem resilience).

Tests run in isolation -- no real Shopify mutations, no real
emails, no persistent state changes. Each test patches a
substrate component to raise/return-error/return-empty and
verifies downstream engines still produce a valid Pattern Q
envelope (i.e. degrade gracefully instead of crashing).

Test classes:
  - observation: funnel/trajectory/earnings handle missing
    data
  - autopilot: writers respect env gates + emergency marker
  - cycle: cycle bridge tolerates each engine failing
  - cross_store: fleet_autopilot tolerates per-store
    exceptions

Bible scoring:
  Q4 (ecosystem resilience): the 20-store empire must NOT
     halt when one substrate piece fails. This engine PROVES
     it doesn't by running the failure paths.

CLI:
  shopai chaos-test                       -- run all tests
  shopai chaos-test --suite observation   -- single suite
  shopai chaos-test --json
"""
from .flow import FleetChaosTestEngine

__all__ = ["FleetChaosTestEngine"]
