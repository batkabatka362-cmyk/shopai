"""Shipping Optimization Engine — delivery time estimator.

Estimates delivery time by zone and carrier.  Handles business-day
conversion (excludes weekends and US federal holidays) and provides
both business-day and calendar-day estimates.

No LLM calls — deterministic calendar math.
"""
from __future__ import annotations

import datetime
from typing import Any


# ---------------------------------------------------------------------------
# US Federal holidays (fixed-date approximations for 2024-2026)
# ---------------------------------------------------------------------------

_FIXED_HOLIDAYS_MD = [
    (1, 1),    # New Year's Day
    (6, 19),   # Juneteenth
    (7, 4),    # Independence Day
    (11, 11),  # Veterans Day
    (12, 25),  # Christmas Day
]

# Floating holidays are approximated with typical dates
_FLOATING_HOLIDAYS: list[tuple[int, int, int]] = [
    # (month, weekday_iso, occurrence)  — weekday: 1=Mon
    # MLK Day: 3rd Monday in January
    (1, 1, 3),
    # Presidents' Day: 3rd Monday in February
    (2, 1, 3),
    # Memorial Day: last Monday in May
    (5, 1, -1),
    # Labor Day: 1st Monday in September
    (9, 1, 1),
    # Thanksgiving: 4th Thursday in November
    (11, 4, 4),
]


def _get_holidays_for_year(year: int) -> set[datetime.date]:
    """Build a set of holiday dates for the given year."""
    holidays: set[datetime.date] = set()

    for m, d in _FIXED_HOLIDAYS_MD:
        holidays.add(datetime.date(year, m, d))

    for month, weekday_iso, occurrence in _FLOATING_HOLIDAYS:
        if occurrence > 0:
            # nth occurrence of weekday in month
            first = datetime.date(year, month, 1)
            # Offset to first matching weekday
            delta = (weekday_iso - first.isoweekday()) % 7
            candidate = first + datetime.timedelta(days=delta)
            candidate += datetime.timedelta(weeks=occurrence - 1)
            holidays.add(candidate)
        else:
            # Last occurrence of weekday in month
            if month == 12:
                last_day = datetime.date(year, 12, 31)
            else:
                last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
            delta = (last_day.isoweekday() - weekday_iso) % 7
            candidate = last_day - datetime.timedelta(days=delta)
            holidays.add(candidate)

    return holidays


def _add_business_days(
    start: datetime.date,
    business_days: int,
    holidays: set[datetime.date],
) -> datetime.date:
    """Add N business days to a start date, skipping weekends and holidays."""
    current = start
    added = 0
    while added < business_days:
        current += datetime.timedelta(days=1)
        if current.isoweekday() <= 5 and current not in holidays:
            added += 1
    return current


# ---------------------------------------------------------------------------
# Carrier transit tables (business days by zone)
# ---------------------------------------------------------------------------

_TRANSIT_TABLES: dict[str, dict[str, dict[int, tuple[int, int]]]] = {
    "USPS": {
        "ground_advantage": {1: (2, 3), 2: (2, 4), 3: (3, 5), 4: (3, 6), 5: (4, 7), 6: (5, 8), 7: (6, 9), 8: (7, 10)},
        "priority_mail": {1: (1, 2), 2: (1, 2), 3: (1, 3), 4: (2, 3), 5: (2, 3), 6: (2, 3), 7: (2, 3), 8: (2, 3)},
        "priority_mail_express": {1: (1, 1), 2: (1, 1), 3: (1, 2), 4: (1, 2), 5: (1, 2), 6: (1, 2), 7: (1, 2), 8: (1, 2)},
    },
    "UPS": {
        "ground": {1: (1, 2), 2: (1, 3), 3: (2, 4), 4: (3, 5), 5: (3, 5), 6: (4, 6), 7: (5, 7), 8: (5, 7)},
        "3_day_select": {1: (1, 2), 2: (1, 2), 3: (2, 3), 4: (2, 3), 5: (3, 3), 6: (3, 3), 7: (3, 3), 8: (3, 3)},
        "2nd_day_air": {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2), 5: (2, 2), 6: (2, 2), 7: (2, 2), 8: (2, 2)},
        "next_day_air": {1: (1, 1), 2: (1, 1), 3: (1, 1), 4: (1, 1), 5: (1, 1), 6: (1, 1), 7: (1, 1), 8: (1, 1)},
    },
    "FedEx": {
        "ground": {1: (1, 2), 2: (1, 3), 3: (2, 4), 4: (2, 5), 5: (3, 5), 6: (4, 6), 7: (4, 7), 8: (5, 7)},
        "express_saver": {1: (1, 2), 2: (2, 3), 3: (2, 3), 4: (3, 3), 5: (3, 3), 6: (3, 3), 7: (3, 3), 8: (3, 3)},
        "2day": {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2), 5: (2, 2), 6: (2, 2), 7: (2, 2), 8: (2, 2)},
        "overnight": {1: (1, 1), 2: (1, 1), 3: (1, 1), 4: (1, 1), 5: (1, 1), 6: (1, 1), 7: (1, 1), 8: (1, 1)},
    },
    "DHL": {
        "ecommerce": {1: (3, 5), 2: (3, 6), 3: (4, 7), 4: (5, 8), 5: (5, 9), 6: (6, 10), 7: (7, 11), 8: (7, 12)},
        "parcel": {1: (2, 3), 2: (2, 4), 3: (3, 5), 4: (3, 5), 5: (4, 6), 6: (4, 7), 7: (5, 7), 8: (5, 8)},
        "express": {1: (1, 1), 2: (1, 1), 3: (1, 2), 4: (1, 2), 5: (1, 2), 6: (1, 2), 7: (1, 2), 8: (2, 2)},
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_delivery(
    zone: int = 5,
    ship_date: str | None = None,
) -> dict[str, Any]:
    """Estimate delivery times for all carriers in a given zone.

    Computes both business-day and calendar-day windows, accounting for
    weekends and US federal holidays.

    Args:
        zone: Shipping zone (1-8).
        ship_date: ISO date string (YYYY-MM-DD) for when the shipment
                   leaves the warehouse.  Defaults to today.

    Returns:
        Structured dict with list of DeliveryEstimate dicts.
    """
    try:
        zone = max(1, min(8, int(zone)))

        if ship_date:
            start = datetime.date.fromisoformat(ship_date)
        else:
            start = datetime.date.today()

        # Build holiday set for current and next year
        holidays = _get_holidays_for_year(start.year) | _get_holidays_for_year(start.year + 1)

        estimates: list[dict[str, Any]] = []

        for carrier, services in _TRANSIT_TABLES.items():
            for service, zone_table in services.items():
                bdays = zone_table.get(zone, (5, 10))
                bday_min, bday_max = bdays

                # Compute calendar days by simulating business-day addition
                arrive_min = _add_business_days(start, bday_min, holidays)
                arrive_max = _add_business_days(start, bday_max, holidays)

                cal_min = (arrive_min - start).days
                cal_max = (arrive_max - start).days

                estimates.append({
                    "carrier": carrier,
                    "service": service,
                    "zone": zone,
                    "business_days_min": bday_min,
                    "business_days_max": bday_max,
                    "calendar_days_min": cal_min,
                    "calendar_days_max": cal_max,
                    "estimated_arrival_earliest": arrive_min.isoformat(),
                    "estimated_arrival_latest": arrive_max.isoformat(),
                })

        # Sort by fastest delivery
        estimates.sort(key=lambda e: (e["business_days_min"], e["business_days_max"]))

        # Summary: group by speed tier
        ground_options = [e for e in estimates if e["business_days_max"] >= 5]
        express_options = [e for e in estimates if 2 <= e["business_days_max"] < 5]
        overnight_options = [e for e in estimates if e["business_days_max"] <= 1]

        return {
            "status": "success",
            "estimates": estimates,
            "count": len(estimates),
            "summary": {
                "zone": zone,
                "ship_date": start.isoformat(),
                "ground_options": len(ground_options),
                "express_options": len(express_options),
                "overnight_options": len(overnight_options),
                "fastest_carrier": estimates[0]["carrier"] if estimates else None,
                "fastest_service": estimates[0]["service"] if estimates else None,
                "fastest_days": estimates[0]["business_days_min"] if estimates else None,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimates": [],
            "count": 0,
            "summary": {},
            "error": f"Delivery estimation failed: {exc}",
        }
