"""modules/ — reusable capability modules.

Per docs/FOLDER_REORG_PLAN.md Phase 2. These are the concrete
business-logic bundles ShopAI composes into an autonomous loop:
risk, crisis, legal, planning, federation, SEO, fulfillment,
compliance.
"""
from __future__ import annotations

# L7 governance
try:
    from core.risk.tripwire import (  # noqa: F401
        RiskTripwire,
        TripwireLimits,
        TripwireVerdict,
        get_risk_tripwire,
    )
except Exception:  # noqa: BLE001
    RiskTripwire = None         # type: ignore[assignment]
    TripwireLimits = None       # type: ignore[assignment]
    TripwireVerdict = None      # type: ignore[assignment]
    get_risk_tripwire = None    # type: ignore[assignment]

# LX.4 crisis response
try:
    from core.crisis.response import (  # noqa: F401
        CrisisResponder,
        CrisisEvent,
        CrisisState,
        get_crisis_responder,
    )
except Exception:  # noqa: BLE001
    CrisisResponder = None          # type: ignore[assignment]
    CrisisEvent = None              # type: ignore[assignment]
    CrisisState = None              # type: ignore[assignment]
    get_crisis_responder = None     # type: ignore[assignment]

# L7 legal
try:
    from core.legal.compliance import (  # noqa: F401
        LegalPageSet,
        render_legal_pages,
    )
except Exception:  # noqa: BLE001
    LegalPageSet = None          # type: ignore[assignment]
    render_legal_pages = None    # type: ignore[assignment]

# EU AI Act (Wave A-4)
try:
    from execution.compliance.eu_ai_act_gate import (  # noqa: F401
        EUAIActGate,
        Creative,
        C2PAManifest,
        get_eu_ai_gate,
    )
except Exception:  # noqa: BLE001
    EUAIActGate = None              # type: ignore[assignment]
    Creative = None                 # type: ignore[assignment]
    C2PAManifest = None             # type: ignore[assignment]
    get_eu_ai_gate = None           # type: ignore[assignment]

# L4 planning
try:
    from core.planning.quarterly_planner import (  # noqa: F401
        QuarterlyGoal,
        QuarterlyPlan,
        build_quarterly_plan,
        check_in,
    )
except Exception:  # noqa: BLE001
    QuarterlyGoal = None            # type: ignore[assignment]
    QuarterlyPlan = None            # type: ignore[assignment]
    build_quarterly_plan = None     # type: ignore[assignment]
    check_in = None                 # type: ignore[assignment]

# LX.5 federation
try:
    from core.federation import (  # noqa: F401
        MultiStoreFederator,
        get_federator,
    )
except Exception:  # noqa: BLE001
    MultiStoreFederator = None      # type: ignore[assignment]
    get_federator = None            # type: ignore[assignment]

# L6 SEO
try:
    from execution.seo.seo_skill import (  # noqa: F401
        generate_product_seo,
        ProductSEO,
    )
    from execution.seo.schema_stack import (  # noqa: F401
        AuthorEntity,
        build_schema_stack,
    )
    from execution.seo.llms_txt import (  # noqa: F401
        build_llms_txt,
    )
except Exception:  # noqa: BLE001
    generate_product_seo = None     # type: ignore[assignment]
    ProductSEO = None               # type: ignore[assignment]
    AuthorEntity = None             # type: ignore[assignment]
    build_schema_stack = None       # type: ignore[assignment]
    build_llms_txt = None           # type: ignore[assignment]

# LX.2 fulfillment + landed cost
try:
    from core.adapters.fulfillment import (  # noqa: F401
        CJFulfillAdapter,
    )
    from execution.fulfillment.landed_cost import (  # noqa: F401
        LandedCostInput,
        calculate_landed_cost,
        minimum_retail_for_margin,
    )
except Exception:  # noqa: BLE001
    CJFulfillAdapter = None              # type: ignore[assignment]
    LandedCostInput = None               # type: ignore[assignment]
    calculate_landed_cost = None         # type: ignore[assignment]
    minimum_retail_for_margin = None     # type: ignore[assignment]


__all__ = [
    "AuthorEntity",
    "C2PAManifest",
    "CJFulfillAdapter",
    "CrisisEvent",
    "CrisisResponder",
    "CrisisState",
    "Creative",
    "EUAIActGate",
    "LandedCostInput",
    "LegalPageSet",
    "MultiStoreFederator",
    "ProductSEO",
    "QuarterlyGoal",
    "QuarterlyPlan",
    "RiskTripwire",
    "TripwireLimits",
    "TripwireVerdict",
    "build_llms_txt",
    "build_quarterly_plan",
    "build_schema_stack",
    "calculate_landed_cost",
    "check_in",
    "generate_product_seo",
    "get_crisis_responder",
    "get_eu_ai_gate",
    "get_federator",
    "get_risk_tripwire",
    "minimum_retail_for_margin",
    "render_legal_pages",
]
