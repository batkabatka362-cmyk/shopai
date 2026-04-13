"""Analysis Layer — configuration."""

ANALYSIS_LAYER_CONFIG = {
    "engines": [
        "market_research",
        "competition_analyzer",
        "trend_detection",
        "demand_analysis",
        "forecasting",
        "opportunity_detection",
        "opportunity_scoring",
    ],
    "required_engines": [
        "market_research",
        "competition_analyzer",
        "trend_detection",
    ],
    "optional_engines": [
        "demand_analysis",
        "forecasting",
        "opportunity_detection",
        "opportunity_scoring",
    ],
    "parallel_groups": [
        ["market_research", "competition_analyzer"],
    ],
}
