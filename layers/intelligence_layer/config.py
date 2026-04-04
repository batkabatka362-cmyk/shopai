"""Intelligence Layer — configuration.

Only simulation_lab and learning_loop are required.
auto_research depends on web connectivity.
global_brain and meta_governance need accumulated runtime data.
"""

INTELLIGENCE_LAYER_CONFIG = {
    "engines": [
        "simulation_lab",
        "auto_research",
        "learning_loop",
        "global_brain",
        "meta_governance",
    ],
    "required_engines": [
        "simulation_lab",
        "learning_loop",
    ],
    "optional_engines": [
        "auto_research",
        "global_brain",
        "meta_governance",
    ],
    "parallel_groups": [],
}
