"""EventType — all system event types."""
from __future__ import annotations
from enum import Enum


class EventType(Enum):
    # Engine lifecycle
    ENGINE_START = "engine.start"
    ENGINE_COMPLETE = "engine.complete"
    ENGINE_FAILED = "engine.failed"
    ENGINE_REJECTED = "engine.rejected"

    # Step lifecycle
    STEP_START = "step.start"
    STEP_COMPLETE = "step.complete"
    STEP_FAILED = "step.failed"

    # Data events
    DATA_VALIDATED = "data.validated"
    DATA_ENRICHED = "data.enriched"
    DATA_ANOMALY = "data.anomaly"

    # Chain events
    CHAIN_START = "chain.start"
    CHAIN_COMPLETE = "chain.complete"
    CHAIN_FAILED = "chain.failed"

    # System events
    SYSTEM_HEALTH_CHECK = "system.health_check"
    SYSTEM_RECOVERY = "system.recovery"
    SYSTEM_ALERT = "system.alert"

    # Learning events
    FEEDBACK_RECORDED = "learning.feedback"
    IMPROVEMENT_PROPOSED = "learning.improvement"
    PATTERN_DETECTED = "learning.pattern"

    # Cache events
    CACHE_HIT = "cache.hit"
    CACHE_MISS = "cache.miss"
    CACHE_EVICTION = "cache.eviction"
