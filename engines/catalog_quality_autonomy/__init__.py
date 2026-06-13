"""Catalog quality autonomy domain (Wave 436+).

9th production autonomy domain. Auto-tags products with quality
flags identified by upstream engines (product_validation,
product_optimization) via SHOPIFY_TAG_PRODUCT.

5-piece template (Phase 12+ wrappers around core/automation/*):
  - quality_log     event journal
  - quality_state   pause flag
  - quality_health  failure-ratio analyzer + bridge
  - quality_applier curated-taxonomy tag writer
  - quality_status  empire-wide rollup
"""
