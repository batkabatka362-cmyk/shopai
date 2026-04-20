"""flow/ — workflow + plan documents.

Per docs/FOLDER_REORG_PLAN.md Phase 2. Collects the
runtime-relevant workflow / cycle / plan modules so "where is
the current cycle logic?" has one answer.

Physical modules live in ``workflows/``, ``core/autonomous``,
``agents/learning/launch_learner`` etc.
"""
from __future__ import annotations

try:
    from agents.learning.launch_learner import (  # noqa: F401
        LaunchLearner,
    )
    from agents.learning.launch_digest import (  # noqa: F401
        LaunchDigest,
        compose_digest,
    )
except Exception:  # noqa: BLE001
    LaunchLearner = None        # type: ignore[assignment]
    LaunchDigest = None         # type: ignore[assignment]
    compose_digest = None       # type: ignore[assignment]

try:
    from core.memory.consolidator import (  # noqa: F401
        MemoryConsolidator,
        get_consolidator,
    )
except Exception:  # noqa: BLE001
    MemoryConsolidator = None       # type: ignore[assignment]
    get_consolidator = None         # type: ignore[assignment]

try:
    from core.learning.rulebook import (  # noqa: F401
        RuleBook,
        get_rulebook,
    )
    from core.learning.pattern_miner import (  # noqa: F401
        PatternMiner,
    )
    from core.learning.llm_pattern_miner import (  # noqa: F401
        LLMPatternMiner,
    )
except Exception:  # noqa: BLE001
    RuleBook = None             # type: ignore[assignment]
    get_rulebook = None         # type: ignore[assignment]
    PatternMiner = None         # type: ignore[assignment]
    LLMPatternMiner = None      # type: ignore[assignment]


__all__ = [
    "LLMPatternMiner",
    "LaunchDigest",
    "LaunchLearner",
    "MemoryConsolidator",
    "PatternMiner",
    "RuleBook",
    "compose_digest",
    "get_consolidator",
    "get_rulebook",
]
