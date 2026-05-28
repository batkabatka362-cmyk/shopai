"""Fulfillment autonomy domain (Wave 126-131).

3rd autonomy domain built on top of core/automation/* template
(Wave 117-120). Proves the reusable substrate works:

  - fulfillment_log     -- thin wrapper over action_log
  - fulfillment_state   -- thin wrapper over pause_state
  - fulfillment_health  -- thin wrapper over health_analyzer
  - fulfillment_applier -- the domain-specific applier
  - fulfillment_status  -- empire-wide aggregator

Each module is ~30 lines instead of ~150 because the boilerplate
lives in core/automation/. Pattern proven reusable.
"""
