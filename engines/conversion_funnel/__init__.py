"""Conversion Funnel Engine — W963-25.

Surfaces the funnel drop-off per stage: sessions -> cart-add ->
checkout-started -> checkout-completed (paid). The single
highest-leverage CRO diagnostic for a cold-start operator —
shows WHERE to focus before firing more cycles.

Hydrates abandoned-checkout + order counts via the existing
Shopify adapters, infers session/cart-add ratios from
analytics-style fields when available, falls back to "unknown"
when not. The verdict identifies the WORST drop and points at
the engine that targets it.

CLI:
  shopai funnel                  -- 7d window
  shopai funnel --days 14
  shopai funnel --store STORE
  shopai funnel --json
"""
from .flow import ConversionFunnelEngine

__all__ = ["ConversionFunnelEngine"]
