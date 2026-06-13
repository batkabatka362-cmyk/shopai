"""Discount cleanup autonomy domain (Wave 154-159).

5th autonomy domain using core/automation/* template.
Closes a real operator pain point: discount codes accumulate
over time (every promo + per-customer recovery code +
operator one-offs) until the store admin lists thousands of
inactive codes. This autonomy domain detects + deactivates
codes that:

  - Have endsAt in the past
  - Have 0 usages + were created >30 days ago
  - Were marked deprecated by upstream engines

Mirrors fulfillment_autonomy + inventory_autonomy in shape.
"""
