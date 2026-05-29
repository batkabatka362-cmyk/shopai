"""Shipping Alert autonomy domain (Wave 756+).

Production autonomy domain scaffolded via shopai autonomy-init.

5-piece template (Phase 12+ wrappers around core/automation/*):
  - shipping_log     event journal
  - shipping_state   pause flag
  - shipping_health  failure-ratio analyzer + bridge
  - shipping_applier curated-taxonomy tag writer
  - shipping_status  empire-wide rollup
"""
