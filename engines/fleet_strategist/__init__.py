"""Fleet Strategist Engine — W963-35.

Fleet-wide AGI brain. Iterates store_strategist (W963-28) over
every store in the fleet, ranks stores by urgency × potential,
emits a single prioritized operator action list.

At 20-store scale, operator scans ONE output instead of N. This
is the direct bible Q1 (20-store leverage) capstone.

Bible scoring:
  Q1 (20-store leverage): operator burden becomes O(1) not O(N).
     At 20 stores, that's the difference between 20 dashboards
     and 1 ranked list.
  Q2 (substrate composability): composes store_strategist +
     StoreManager + active_store + earnings_by_engine. Zero
     new substrate.
  Q3 (AI self-learning): the ranking heuristic (urgency ×
     log(revenue)) is the deterministic baseline future LLM
     fleet brain layers on top of.

Ranking
-------
For each store:
  1. Run store_strategist → get verdict + top recommendation
  2. urgency_score = top_rec.priority_score (0..1)
  3. revenue_weight = log10(7d_revenue + 10)
     — log to avoid one mega-store drowning the rest
  4. fleet_priority = urgency × revenue_weight

Stores sorted desc by fleet_priority. Cold-start stores (zero
revenue) bubble to a separate "cold_start" bucket so they don't
get lost in the noise.

CLI:
  shopai fleet-strategist               -- all stores, ranked
  shopai fleet-strategist --top 5       -- top 5 only
  shopai fleet-strategist --verdict intervene  -- filter
  shopai fleet-strategist --json
"""
from .flow import FleetStrategistEngine

__all__ = ["FleetStrategistEngine"]
