"""Action Planner — reference data: plan templates, budget allocations, milestones.

Provides week-by-week plan templates by product type, standard budget
allocation percentages per action type, and milestone definitions with
success criteria.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Plan templates by product type (week-by-week steps)
# ---------------------------------------------------------------------------
PLAN_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "general": [
        {
            "week": 1,
            "title": "Order Samples & Validate Quality",
            "description": "Order 2-3 samples from the top supplier. Inspect quality, packaging, and shipping time.",
            "action_type": "quality",
            "phase": "sample_validation",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
        {
            "week": 2,
            "title": "Create Product Listing",
            "description": "Write optimized title, bullet points, and description. Take professional product photos.",
            "action_type": "listing",
            "phase": "preparation",
            "priority": "high",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 3,
            "title": "Place Initial Inventory Order",
            "description": "Order initial batch based on 30-day demand projection. Negotiate best terms.",
            "action_type": "inventory",
            "phase": "preparation",
            "priority": "high",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 4,
            "title": "Launch Product & Start PPC",
            "description": "Publish listing, set competitive launch price, start PPC campaigns with $20-30/day budget.",
            "action_type": "marketing",
            "phase": "launch",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
        {
            "week": 5,
            "title": "Monitor & Optimize",
            "description": "Track sales velocity, ACOS, and conversion rate daily. Adjust bids and keywords.",
            "action_type": "marketing",
            "phase": "optimization",
            "priority": "medium",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 6,
            "title": "30-Day Performance Review",
            "description": "Evaluate against success criteria: sales volume, margin, ACOS, reviews. Decide to scale or pivot.",
            "action_type": "review",
            "phase": "review",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
        {
            "week": 8,
            "title": "Scale or Adjust",
            "description": "If metrics are positive, increase inventory and ad spend. If not, execute contingency plan.",
            "action_type": "inventory",
            "phase": "scaling",
            "priority": "medium",
            "is_milestone": False,
            "notes": "",
        },
    ],
    "electronics": [
        {
            "week": 1,
            "title": "Order Samples & Test Certifications",
            "description": "Order samples. Verify FCC/CE certifications, test functionality, check packaging durability.",
            "action_type": "quality",
            "phase": "sample_validation",
            "priority": "high",
            "is_milestone": True,
            "notes": "Electronics require compliance testing.",
        },
        {
            "week": 2,
            "title": "Create Technical Listing",
            "description": "Write detailed specs, create comparison charts, take demo photos and video.",
            "action_type": "listing",
            "phase": "preparation",
            "priority": "high",
            "is_milestone": False,
            "notes": "Include technical specifications and compatibility info.",
        },
        {
            "week": 3,
            "title": "Order Initial Inventory",
            "description": "Place order with verified supplier. Request quality inspection before shipping.",
            "action_type": "inventory",
            "phase": "preparation",
            "priority": "high",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 4,
            "title": "Launch with Targeted PPC",
            "description": "Launch listing, target specific technical keywords, set launch pricing.",
            "action_type": "marketing",
            "phase": "launch",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
        {
            "week": 5,
            "title": "Monitor Returns & Reviews",
            "description": "Electronics have higher return rates — monitor daily and address quality issues immediately.",
            "action_type": "review",
            "phase": "optimization",
            "priority": "high",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 6,
            "title": "30-Day Performance Review",
            "description": "Evaluate sales, return rate (target under 5%), margin, and customer feedback.",
            "action_type": "review",
            "phase": "review",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
    ],
    "apparel": [
        {
            "week": 1,
            "title": "Order Size Run Samples",
            "description": "Order samples in multiple sizes. Check fabric quality, stitching, and sizing accuracy.",
            "action_type": "quality",
            "phase": "sample_validation",
            "priority": "high",
            "is_milestone": True,
            "notes": "Apparel requires size validation across the range.",
        },
        {
            "week": 2,
            "title": "Create Visual Listing",
            "description": "Professional photography with models, create size chart, write lifestyle-focused copy.",
            "action_type": "listing",
            "phase": "preparation",
            "priority": "high",
            "is_milestone": False,
            "notes": "Multiple angles and on-model shots are essential.",
        },
        {
            "week": 3,
            "title": "Order Initial Size Distribution",
            "description": "Order based on standard size curve (S:M:L:XL = 15:30:30:25). Small initial batch.",
            "action_type": "inventory",
            "phase": "preparation",
            "priority": "high",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 4,
            "title": "Launch with Visual Ads",
            "description": "Sponsored brand ads with lifestyle imagery, target fashion/style keywords.",
            "action_type": "marketing",
            "phase": "launch",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
        {
            "week": 5,
            "title": "Monitor Sizing Feedback",
            "description": "Track size-related returns and reviews. Adjust size chart if needed.",
            "action_type": "review",
            "phase": "optimization",
            "priority": "high",
            "is_milestone": False,
            "notes": "",
        },
        {
            "week": 6,
            "title": "30-Day Performance Review",
            "description": "Evaluate sales by size, return rate (target under 15%), margin, and repeat purchases.",
            "action_type": "review",
            "phase": "review",
            "priority": "high",
            "is_milestone": True,
            "notes": "",
        },
    ],
}

# ---------------------------------------------------------------------------
# Budget allocation percentages by action type
# ---------------------------------------------------------------------------
BUDGET_ALLOCATIONS: dict[str, dict[str, Any]] = {
    "quality": {
        "percentage": 5,
        "description": "Sample orders and quality testing",
        "typical_range": "$50-500",
    },
    "listing": {
        "percentage": 5,
        "description": "Photography, copywriting, and listing optimization",
        "typical_range": "$100-500",
    },
    "inventory": {
        "percentage": 50,
        "description": "Initial inventory purchase and shipping",
        "typical_range": "40-60% of total investment",
    },
    "marketing": {
        "percentage": 25,
        "description": "PPC campaigns, sponsored ads, and promotions",
        "typical_range": "20-30% of total investment",
    },
    "review": {
        "percentage": 0,
        "description": "Review and evaluation — no direct cost",
        "typical_range": "$0 (time investment only)",
    },
    "other": {
        "percentage": 5,
        "description": "Miscellaneous and contingency",
        "typical_range": "5-10% of total investment",
    },
}

# ---------------------------------------------------------------------------
# Milestone definitions with success criteria
# ---------------------------------------------------------------------------
MILESTONE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "sample_validation": {
        "success_criteria": (
            "Samples pass quality inspection: material quality matches description, "
            "no defects, packaging intact after shipping, matches supplier photos."
        ),
        "decision_point": "Go/No-Go: proceed to inventory order or find new supplier",
        "failure_action": "Request replacement samples or switch to backup supplier",
    },
    "launch": {
        "success_criteria": (
            "Listing is live with optimized content, PPC campaign running, "
            "first impressions and clicks being tracked. Target: at least 100 "
            "impressions in first 48 hours."
        ),
        "decision_point": "Confirm listing is indexed and ads are serving",
        "failure_action": "Debug listing issues, check keyword indexing, adjust bids",
    },
    "review": {
        "success_criteria": (
            "30-day results: positive unit economics (actual margin within 5% of "
            "projection), ACOS below 30%, at least 1 review, return rate under 10%."
        ),
        "decision_point": "Scale up, maintain, or exit based on metrics",
        "failure_action": (
            "If margin is negative: adjust pricing or reduce ad spend. "
            "If no sales: revise listing and keywords. "
            "If high returns: investigate quality issues."
        ),
    },
    "default": {
        "success_criteria": "Step completed on time and within budget",
        "decision_point": "Proceed to next step if criteria met",
        "failure_action": "Investigate blockers and adjust timeline",
    },
}
