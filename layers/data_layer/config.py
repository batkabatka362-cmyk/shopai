"""Data Layer — configuration."""

DATA_LAYER_CONFIG = {
    "engines": [
        "data_collection",
        "data_enrichment",
        "behavioral_data",
        "event_tracking",
        "user_tracking",
    ],
    "required_engines": ["data_collection"],
    "optional_engines": [
        "data_enrichment",
        "behavioral_data",
        "event_tracking",
        "user_tracking",
    ],
    "parallel_groups": [],
}
