"""Lead time reference data — shipping times, customs, carrier ratings.

All transit times in calendar days. Cost estimates in USD.
Data reflects 2024-2025 averages from major trade lanes.
"""
from __future__ import annotations


# --- Shipping transit times by method and route ---
# Format: method -> { route -> {min, typical, max}, cost_per_kg }
SHIPPING_TIMES: dict = {
    "sea": {
        "CN>US":  {"min": 18, "typical": 28, "max": 45},   # West coast; +5-7 for east coast
        "CN>EU":  {"min": 25, "typical": 35, "max": 50},   # To Rotterdam/Hamburg
        "CN>UK":  {"min": 28, "typical": 38, "max": 55},   # Post-Brexit separate entry
        "CN>AU":  {"min": 14, "typical": 22, "max": 35},   # Shorter route
        "CN>CA":  {"min": 16, "typical": 25, "max": 40},   # Vancouver port
        "US>US":  {"min": 3,  "typical": 5,  "max": 8},    # Domestic ground
        "EU>EU":  {"min": 2,  "typical": 4,  "max": 7},    # Intra-EU truck/rail
        "default": {"min": 20, "typical": 30, "max": 50},
        "cost_per_kg": 0.50,  # $0.30-0.80 typical, using midpoint
    },
    "air": {
        "CN>US":  {"min": 5,  "typical": 8,  "max": 14},
        "CN>EU":  {"min": 5,  "typical": 9,  "max": 15},
        "CN>UK":  {"min": 5,  "typical": 9,  "max": 15},
        "CN>AU":  {"min": 4,  "typical": 7,  "max": 12},
        "CN>CA":  {"min": 5,  "typical": 8,  "max": 13},
        "US>US":  {"min": 1,  "typical": 3,  "max": 5},
        "EU>EU":  {"min": 1,  "typical": 3,  "max": 5},
        "default": {"min": 5, "typical": 10, "max": 18},
        "cost_per_kg": 4.50,  # $3-6 typical
    },
    "express": {
        "CN>US":  {"min": 3,  "typical": 5,  "max": 8},    # DHL/FedEx/UPS
        "CN>EU":  {"min": 3,  "typical": 5,  "max": 9},
        "CN>UK":  {"min": 3,  "typical": 5,  "max": 9},
        "CN>AU":  {"min": 3,  "typical": 5,  "max": 8},
        "CN>CA":  {"min": 3,  "typical": 5,  "max": 8},
        "US>US":  {"min": 1,  "typical": 2,  "max": 4},
        "EU>EU":  {"min": 1,  "typical": 2,  "max": 4},
        "default": {"min": 3, "typical": 6, "max": 10},
        "cost_per_kg": 12.00,  # $8-25 typical, varies by weight
    },
    "rail": {
        "CN>EU":  {"min": 16, "typical": 22, "max": 30},   # China-Europe rail (Yiwu-London)
        "CN>UK":  {"min": 18, "typical": 25, "max": 35},
        "default": {"min": 16, "typical": 22, "max": 35},
        "cost_per_kg": 2.00,  # Between sea and air
    },
}

# --- Customs processing times by country (calendar days) ---
CUSTOMS_PROCESSING: dict = {
    "US":  {"min": 1, "typical": 3, "max": 10,  "notes": "CBP clearance; FDA adds 2-5 days"},
    "EU":  {"min": 1, "typical": 3, "max": 8,   "notes": "Single entry; varies by port"},
    "UK":  {"min": 1, "typical": 4, "max": 12,  "notes": "Post-Brexit delays common"},
    "CA":  {"min": 1, "typical": 3, "max": 8,   "notes": "CBSA processing"},
    "AU":  {"min": 2, "typical": 5, "max": 14,  "notes": "Strict biosecurity inspections"},
    "JP":  {"min": 1, "typical": 2, "max": 5,   "notes": "Efficient processing"},
    "BR":  {"min": 5, "typical": 14, "max": 45, "notes": "Notoriously slow; plan accordingly"},
    "IN":  {"min": 3, "typical": 7, "max": 21,  "notes": "Complex duty structure"},
    "MX":  {"min": 2, "typical": 5, "max": 15,  "notes": "Customs broker essential"},
    "default": {"min": 2, "typical": 5, "max": 14, "notes": "Estimate for unlisted countries"},
}

# --- Carrier reliability ratings ---
# on_time_pct: percentage of shipments delivered within quoted window
CARRIER_RELIABILITY: dict = {
    "dhl":      {"on_time_pct": 0.92, "tier": "premium",  "tracking": "excellent", "claim_ease": "good"},
    "fedex":    {"on_time_pct": 0.90, "tier": "premium",  "tracking": "excellent", "claim_ease": "good"},
    "ups":      {"on_time_pct": 0.89, "tier": "premium",  "tracking": "excellent", "claim_ease": "moderate"},
    "maersk":   {"on_time_pct": 0.78, "tier": "standard", "tracking": "good",      "claim_ease": "slow"},
    "cosco":    {"on_time_pct": 0.74, "tier": "budget",   "tracking": "moderate",  "claim_ease": "slow"},
    "evergreen": {"on_time_pct": 0.73, "tier": "budget",  "tracking": "moderate",  "claim_ease": "slow"},
    "msc":      {"on_time_pct": 0.72, "tier": "budget",   "tracking": "moderate",  "claim_ease": "slow"},
    "yanwen":   {"on_time_pct": 0.65, "tier": "economy",  "tracking": "poor",      "claim_ease": "difficult"},
    "cainiao":  {"on_time_pct": 0.70, "tier": "economy",  "tracking": "moderate",  "claim_ease": "difficult"},
    "epacket":  {"on_time_pct": 0.62, "tier": "economy",  "tracking": "poor",      "claim_ease": "none"},
    "unknown":  {"on_time_pct": 0.75, "tier": "unknown",  "tracking": "unknown",   "claim_ease": "unknown"},
}

# --- Peak season delay multipliers ---
# Multiplier applied to typical transit times during these periods.
PEAK_SEASON_DELAYS: dict = {
    "chinese_new_year": {
        "months": [1, 2],
        "multiplier": 1.80,
        "note": "Factories close 2-4 weeks. Backlogs last another 2-3 weeks after reopening.",
    },
    "golden_week_china": {
        "months": [10],
        "multiplier": 1.30,
        "note": "1-week holiday; production pauses but shipping continues.",
    },
    "q4_peak": {
        "months": [10, 11, 12],
        "multiplier": 1.50,
        "note": "Black Friday / holiday demand. Carrier capacity maxed out. Rates spike 2-3x.",
    },
    "q1_slow": {
        "months": [1, 2, 3],
        "multiplier": 1.10,
        "note": "Post-holiday slowdown. Good time to restock at lower rates.",
    },
    "summer_lull": {
        "months": [7, 8],
        "multiplier": 0.95,
        "note": "Lower volume. Slightly faster processing and better rates.",
    },
}


def get_route_time(origin: str, destination: str, method: str = "sea") -> dict:
    """Convenience lookup for a specific route and method."""
    ship = SHIPPING_TIMES.get(method, SHIPPING_TIMES["sea"])
    route_key = f"{origin}>{destination}"
    return ship.get(route_key, ship.get("default", {"min": 10, "typical": 20, "max": 40}))
