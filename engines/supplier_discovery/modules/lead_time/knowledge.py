"""Lead time expert knowledge — hard-won insights for e-commerce sourcing.

This module captures the tribal knowledge that experienced importers know
but rarely write down. Each function returns structured advice.
"""
from __future__ import annotations

from typing import Any


def get_lead_time_tips() -> list[dict[str, str]]:
    """Actionable tips for reducing and managing lead times."""
    return [
        {
            "tip": "Order samples before committing",
            "detail": "A sample order reveals real production time, packaging quality, "
                      "and shipping speed. Budget 2-3 weeks and $50-200 for samples.",
        },
        {
            "tip": "Overlap production and shipping prep",
            "detail": "Have your freight forwarder book vessel space while production "
                      "finishes. Saves 3-7 days vs sequential booking.",
        },
        {
            "tip": "Use a sourcing agent in-country",
            "detail": "A local agent can visit the factory, inspect goods before shipping, "
                      "and push for on-time production. Cost: 3-7% of order value.",
        },
        {
            "tip": "Negotiate partial shipments",
            "detail": "Get 30% of the order via air to start selling while the rest "
                      "comes by sea. Higher shipping cost but faster cash flow.",
        },
        {
            "tip": "Keep a safety stock SKU-level buffer",
            "detail": "Top 20% of SKUs should have 30-45 days of safety stock. "
                      "Long-tail items can run leaner at 15-20 days.",
        },
        {
            "tip": "Pre-clear customs electronically",
            "detail": "File ISF (Importer Security Filing) 72 hours before vessel arrival. "
                      "Goods clear faster and avoid warehouse demurrage fees.",
        },
        {
            "tip": "Build relationships with 2-3 suppliers per product",
            "detail": "Single-source risk is real. A backup supplier with tested samples "
                      "means you can pivot in 48 hours if your primary fails.",
        },
        {
            "tip": "Track and measure actual vs quoted lead times",
            "detail": "Keep a spreadsheet of every order: date placed, date shipped, "
                      "date received. This data is your negotiating leverage.",
        },
    ]


def get_cny_impact() -> dict[str, Any]:
    """Chinese New Year disruption guide.

    CNY is the single biggest supply chain disruption for e-commerce
    sellers sourcing from China. It affects ALL Chinese suppliers.
    """
    return {
        "event": "Chinese New Year (Spring Festival)",
        "duration": "Official: 7 days. Actual disruption: 4-6 weeks.",
        "typical_dates": "Late January to mid-February (varies yearly by lunar calendar)",
        "timeline": {
            "6_weeks_before": "Workers start leaving for home provinces. "
                              "Production quality drops as temporary workers fill gaps.",
            "2_weeks_before": "Most factories at 50-70% capacity. "
                              "Shipping lines fully booked. Rates spike.",
            "during_cny": "Complete shutdown. No production, no shipping, no communication. "
                          "Factories close 2-4 weeks.",
            "2_weeks_after": "Factories reopen but at 40-60% capacity. "
                             "Workers trickle back. Some never return (10-20% turnover).",
            "4_weeks_after": "Production normalizes. Backlog from CNY orders clears.",
        },
        "action_plan": [
            "Place all Q1 orders by November 15 at the latest.",
            "Stock 60-90 days of inventory before CNY period.",
            "Confirm production completion and shipping before January 10.",
            "Pre-book freight — carrier space sells out by early January.",
            "Expect 30-50% shipping rate increases during this window.",
            "Budget for air freight backup if sea shipments miss the cutoff.",
        ],
        "cost_impact": "15-30% higher total landed cost during CNY period.",
    }


def get_peak_season_guide() -> dict[str, Any]:
    """Q4 peak season planning for e-commerce sellers."""
    return {
        "overview": "Q4 (October-December) is make-or-break for e-commerce. "
                    "60-70% of annual profit comes from this period for many sellers.",
        "critical_deadlines": {
            "july": "Finalize Q4 product selection and place initial orders.",
            "august": "Production should be underway. Book freight for September shipping.",
            "september_1": "LAST CALL for sea freight to arrive by mid-October. "
                           "After this, air freight is the only option.",
            "october_1": "All Q4 inventory should be in-country or in transit via air.",
            "october_15": "Amazon FBA inventory check-in deadline for Black Friday.",
            "november": "Restock only via express/air. Sea freight will not arrive in time.",
        },
        "common_mistakes": [
            "Ordering too late — 'I'll order in October' means you miss Black Friday.",
            "Underestimating demand — better to overstock 20% than stockout during peak.",
            "Ignoring carrier surcharges — rates double or triple in Q4.",
            "Not booking freight early — space sells out, especially for Amazon sellers.",
            "Single carrier dependency — diversify across 2-3 carriers.",
        ],
        "shipping_rate_impact": {
            "sea_freight": "+50-100% vs off-peak rates",
            "air_freight": "+30-60% vs off-peak rates",
            "express": "+20-40% vs off-peak rates, plus surcharges",
        },
    }


def get_incoterms_guide() -> dict[str, Any]:
    """Incoterms explained for e-commerce importers.

    Incoterms define who pays for what in international shipping.
    Getting this wrong means surprise costs at the port.
    """
    return {
        "overview": "Incoterms (International Commercial Terms) define the responsibilities "
                    "of buyer and seller for shipping, insurance, and customs.",
        "common_terms": {
            "EXW": {
                "name": "Ex Works",
                "seller_responsibility": "Make goods available at their facility.",
                "buyer_responsibility": "Everything: pickup, export, freight, import, delivery.",
                "best_for": "Experienced importers with their own freight forwarder.",
                "risk": "Buyer bears all risk from factory door.",
                "tip": "Cheapest quoted price but highest hidden costs. Not recommended for beginners.",
            },
            "FOB": {
                "name": "Free On Board",
                "seller_responsibility": "Deliver to port, export clearance, load onto vessel.",
                "buyer_responsibility": "Ocean freight, insurance, import clearance, delivery.",
                "best_for": "Most e-commerce importers. Good balance of control and simplicity.",
                "risk": "Risk transfers when goods pass the ship's rail.",
                "tip": "Most common for Alibaba orders. You control shipping cost and timeline.",
            },
            "CIF": {
                "name": "Cost, Insurance, and Freight",
                "seller_responsibility": "Everything to destination port including freight and insurance.",
                "buyer_responsibility": "Import clearance, duties, last-mile delivery.",
                "best_for": "Beginners who want the supplier to handle shipping.",
                "risk": "Seller chooses cheapest carrier. Less control over transit time.",
                "tip": "Convenient but you lose control. Supplier's insurance is often minimal.",
            },
            "DDP": {
                "name": "Delivered Duty Paid",
                "seller_responsibility": "Everything including import duties and delivery to your door.",
                "buyer_responsibility": "Nothing — goods arrive ready to sell.",
                "best_for": "Small orders, dropshipping, or when supplier offers competitive DDP rates.",
                "risk": "Highest price but zero hassle. Supplier may undervalue for customs.",
                "tip": "Watch for customs undervaluation — if caught, YOU are liable as importer of record.",
            },
        },
        "recommendation": "Start with FOB for orders over $2,000. Use DDP for small test orders under $500. "
                          "Avoid EXW unless you have a trusted freight forwarder.",
    }


def get_forwarder_tips() -> dict[str, Any]:
    """How to choose and work with a freight forwarder."""
    return {
        "what_they_do": "Freight forwarders coordinate the entire shipping process: "
                        "booking carriers, handling customs paperwork, arranging last-mile delivery.",
        "when_to_use": "Any shipment over $2,000 or 100 kg. Below that, supplier DDP or express is simpler.",
        "selection_criteria": [
            "Experience with your specific trade lane (e.g., Shenzhen to Los Angeles).",
            "Clear, itemized quotes — beware 'all-in' prices that hide fees.",
            "References from other e-commerce sellers (ask in communities).",
            "Responsiveness: a good forwarder replies within 24 hours.",
            "Customs brokerage in-house vs outsourced (in-house is faster).",
        ],
        "red_flags": [
            "No itemized breakdown of costs.",
            "Unwilling to provide references.",
            "Quoted price significantly below market (hidden fees incoming).",
            "Poor communication or slow responses during quoting phase.",
            "No experience with e-commerce or Amazon FBA shipments.",
        ],
        "expected_costs": {
            "sea_freight_fcl_20ft": "$1,500-4,000 (CN to US West Coast)",
            "sea_freight_lcl": "$50-80 per CBM",
            "customs_brokerage": "$100-250 per entry",
            "drayage": "$300-800 (port to warehouse)",
            "forwarder_fee": "$50-150 per shipment",
        },
        "top_tip": "Get quotes from 3 forwarders for every shipment over $5,000. "
                   "Prices vary 20-40% for the same service.",
    }
