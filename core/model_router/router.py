"""Cost-aware model router (policy).

For each AI call the caller hands the router a prompt and an
optional complexity hint; the router returns a
``RoutingDecision`` with the chosen tier + reason. The caller
then runs the model and feeds the measured outcome back via
``record_usage`` so daily budget bookkeeping stays accurate.

Routing policy (default):

  1. ``hint=CLOUD_REQUIRED`` → cloud, no override.
  2. ``hint=LOCAL_ONLY`` → local, no override.
  3. Token estimate < ``local_max_tokens`` (default 512) AND no
     strategy keywords AND prose ratio < 0.7 → local.
  4. Otherwise → cloud.
  5. **Budget override**: if the rolling-24h cloud-call budget
     is exhausted, downgrade cloud → local even when policy
     would prefer cloud. The decision's ``reason`` records the
     downgrade so callers can surface "cloud budget exhausted"
     in their UI.

Why a deterministic policy:
  - Debuggable. An operator can read the ``reason`` field and
    immediately understand why a call went to a given tier.
  - No bootstrap problem. A learned router needs training data
    that doesn't exist until the system has been running. This
    static policy generates that data.
  - The contract is stable -- swap in a small local classifier
    later without breaking callers.
"""
from __future__ import annotations

import enum
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────


# Words that indicate the call needs multi-factor reasoning.
# If any appears in the prompt, classify as cloud.
_STRATEGY_KEYWORDS = {
    "strategy", "strategize",
    "plan", "planning",
    "explain", "explanation",
    "reason", "reasoning",
    "trade-off", "tradeoff", "trade off",
    "compare", "comparison",
    "evaluate", "evaluation",
    "analyze", "analysis",
    "rationale",
    "why",
    "design",
    "synthesize", "synthesise",
    "critique",
    "argument",
    "long-form",
}

# Default token budget: an Opus call ~averages 1k input + 1k output.
# 50 calls / day ≈ 100k tokens, a reasonable starting cap.
_DEFAULT_CLOUD_TOKENS_PER_24H = 100_000

# Words-to-tokens rough conversion. English averages ~1.3
# tokens per word; we round to 1.4 for safety.
_TOKENS_PER_WORD = 1.4


# ── Types ──────────────────────────────────────────────────────


class ModelTier(str, enum.Enum):
    """Which model class a routing decision selected."""
    LOCAL = "local"
    CLOUD = "cloud"


class ModelHint(str, enum.Enum):
    """Caller hint that overrides automatic classification."""
    AUTO = "auto"
    LOCAL_ONLY = "local_only"
    CLOUD_REQUIRED = "cloud_required"


@dataclass
class RoutingDecision:
    """The output of :meth:`ModelRouter.classify`.

    Fields:
        tier: Selected model tier.
        reason: Human-readable explanation (e.g. "short prompt
            + no strategy keywords").
        estimated_tokens: Heuristic prompt-token estimate.
        complexity_score: 0.0 (trivial) → 1.0 (deep reasoning).
        downgraded: True if the policy would have chosen cloud
            but the budget cap forced a downgrade to local.
    """
    tier: ModelTier
    reason: str
    estimated_tokens: int
    complexity_score: float
    downgraded: bool = False
    components: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "reason": self.reason,
            "estimated_tokens": self.estimated_tokens,
            "complexity_score": round(self.complexity_score, 4),
            "downgraded": self.downgraded,
            "components": self.components,
        }


# ── Router ─────────────────────────────────────────────────────


class ModelRouter:
    """Cost-aware model router.

    Construct with an in-memory DB for tests; production callers
    leave ``db_path=None`` to share the process-wide singleton
    file.
    """

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        local_max_tokens: int = 512,
        cloud_tokens_per_24h: int = _DEFAULT_CLOUD_TOKENS_PER_24H,
    ) -> None:
        self._local_max_tokens = int(local_max_tokens)
        self._cloud_tokens_per_24h = int(cloud_tokens_per_24h)
        self._lock = threading.Lock()
        self._conn = self._open(db_path)
        self._init_schema()

    # ── Connection ──────────────────────────────────────────

    def _open(self, db_path: str | Path | None) -> sqlite3.Connection:
        if db_path is None:
            # Default location -- keep alongside other ShopAI DBs.
            db_path = Path("data") / "model_router.db"
            try:
                Path("data").mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "model_router data dir create raised: %s", exc,
                )
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS usage_log (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at REAL NOT NULL,
                    tier TEXT NOT NULL,
                    estimated_tokens INTEGER NOT NULL,
                    actual_tokens INTEGER,
                    latency_ms INTEGER,
                    purpose TEXT,
                    reason TEXT,
                    downgraded INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_usage_tier_time
                    ON usage_log(tier, occurred_at);
            """)
            self._conn.commit()

    # ── Public API ──────────────────────────────────────────

    def classify(
        self,
        prompt: str,
        *,
        hint: ModelHint = ModelHint.AUTO,
        purpose: str | None = None,
    ) -> RoutingDecision:
        """Classify a prompt and return a routing decision.

        Args:
            prompt: The prompt text the model would receive.
            hint: Caller-supplied tier hint. ``AUTO`` (default)
                runs the heuristic classifier. ``LOCAL_ONLY``
                / ``CLOUD_REQUIRED`` bypass the heuristic.
            purpose: Optional label ("intent", "strategy",
                "categorize", ...). Stored verbatim on
                ``record_usage`` so audits can group by intent.

        Returns:
            A :class:`RoutingDecision`.
        """
        estimated_tokens = _estimate_tokens(prompt)
        components = _complexity_components(prompt)
        complexity = _combine_complexity(components)

        # Hint shortcuts.
        if hint == ModelHint.LOCAL_ONLY:
            return RoutingDecision(
                tier=ModelTier.LOCAL,
                reason="hint=LOCAL_ONLY",
                estimated_tokens=estimated_tokens,
                complexity_score=complexity,
                components=components,
            )
        if hint == ModelHint.CLOUD_REQUIRED:
            # Even when caller hints CLOUD_REQUIRED, the budget
            # cap can downgrade. Caller can override with their
            # own model call.
            if self._cloud_exhausted():
                return RoutingDecision(
                    tier=ModelTier.LOCAL,
                    reason="cloud_budget_exhausted (hint was CLOUD_REQUIRED)",
                    estimated_tokens=estimated_tokens,
                    complexity_score=complexity,
                    downgraded=True,
                    components=components,
                )
            return RoutingDecision(
                tier=ModelTier.CLOUD,
                reason="hint=CLOUD_REQUIRED",
                estimated_tokens=estimated_tokens,
                complexity_score=complexity,
                components=components,
            )

        # Heuristic.
        wants_cloud = (
            estimated_tokens > self._local_max_tokens
            or complexity >= 0.5
        )
        if not wants_cloud:
            return RoutingDecision(
                tier=ModelTier.LOCAL,
                reason="short prompt, no strategy signals",
                estimated_tokens=estimated_tokens,
                complexity_score=complexity,
                components=components,
            )
        if self._cloud_exhausted():
            return RoutingDecision(
                tier=ModelTier.LOCAL,
                reason="cloud_budget_exhausted",
                estimated_tokens=estimated_tokens,
                complexity_score=complexity,
                downgraded=True,
                components=components,
            )
        reasons = []
        if estimated_tokens > self._local_max_tokens:
            reasons.append("long prompt")
        if complexity >= 0.5:
            reasons.append("strategy/reasoning signals")
        return RoutingDecision(
            tier=ModelTier.CLOUD,
            reason=", ".join(reasons),
            estimated_tokens=estimated_tokens,
            complexity_score=complexity,
            components=components,
        )

    def record_usage(
        self,
        decision: RoutingDecision,
        *,
        actual_tokens: int | None = None,
        latency_ms: int | None = None,
        purpose: str | None = None,
    ) -> None:
        """Persist a routing decision's outcome.

        Caller invokes this after running the model call. The
        recorded data drives the budget cap on subsequent
        classify() calls.

        Failures don't propagate -- recording is best-effort.
        """
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO usage_log
                       (occurred_at, tier, estimated_tokens,
                        actual_tokens, latency_ms, purpose,
                        reason, downgraded)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        time.time(),
                        decision.tier.value,
                        decision.estimated_tokens,
                        actual_tokens,
                        latency_ms,
                        purpose,
                        decision.reason,
                        1 if decision.downgraded else 0,
                    ),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "model_router record_usage raised: %s", exc,
            )

    def budget_report(self, *, window_hours: int = 24) -> dict[str, Any]:
        """Return a usage rollup over the recent window.

        Includes per-tier call counts, summed estimated + actual
        tokens, and a ``cloud_remaining_estimate_pct`` so callers
        can render "X% of cloud budget remaining today" without
        recomputing.
        """
        cutoff = time.time() - float(window_hours) * 3600.0
        with self._lock:
            rows = self._conn.execute(
                """SELECT tier, COUNT(*) AS calls,
                          SUM(estimated_tokens) AS est_tokens,
                          SUM(COALESCE(actual_tokens, 0)) AS act_tokens,
                          SUM(downgraded) AS downgrades
                   FROM usage_log
                   WHERE occurred_at >= ?
                   GROUP BY tier""",
                (cutoff,),
            ).fetchall()
        by_tier = {
            ModelTier.LOCAL.value: {
                "calls": 0, "estimated_tokens": 0,
                "actual_tokens": 0, "downgrades": 0,
            },
            ModelTier.CLOUD.value: {
                "calls": 0, "estimated_tokens": 0,
                "actual_tokens": 0, "downgrades": 0,
            },
        }
        for r in rows:
            by_tier[r["tier"]] = {
                "calls": int(r["calls"] or 0),
                "estimated_tokens": int(r["est_tokens"] or 0),
                "actual_tokens": int(r["act_tokens"] or 0),
                "downgrades": int(r["downgrades"] or 0),
            }
        cloud_tokens_used = (
            by_tier[ModelTier.CLOUD.value]["actual_tokens"]
            or by_tier[ModelTier.CLOUD.value]["estimated_tokens"]
        )
        remaining_pct = max(
            0.0,
            1.0 - (cloud_tokens_used / self._cloud_tokens_per_24h),
        ) if self._cloud_tokens_per_24h else 0.0
        return {
            "window_hours": int(window_hours),
            "by_tier": by_tier,
            "cloud_tokens_per_24h": self._cloud_tokens_per_24h,
            "cloud_tokens_used": cloud_tokens_used,
            "cloud_remaining_estimate_pct": round(remaining_pct, 4),
        }

    # ── Internals ───────────────────────────────────────────

    def _cloud_exhausted(self) -> bool:
        """Are we over budget on cloud tokens in the last 24h?"""
        cutoff = time.time() - 24.0 * 3600.0
        with self._lock:
            row = self._conn.execute(
                """SELECT SUM(COALESCE(actual_tokens, estimated_tokens))
                       AS used
                   FROM usage_log
                   WHERE tier = ? AND occurred_at >= ?""",
                (ModelTier.CLOUD.value, cutoff),
            ).fetchone()
        used = int(row["used"] or 0)
        return used >= self._cloud_tokens_per_24h


# ── Heuristic helpers ───────────────────────────────────────


def _estimate_tokens(prompt: str) -> int:
    """Word-count-based token estimate (English ~1.4 tok/word)."""
    if not isinstance(prompt, str):
        return 0
    word_count = len(re.findall(r"\b\w+\b", prompt))
    return max(0, int(word_count * _TOKENS_PER_WORD))


def _complexity_components(prompt: str) -> dict[str, Any]:
    """Per-component complexity signals (debuggable)."""
    if not isinstance(prompt, str):
        prompt = ""
    lower = prompt.lower()
    keyword_hits = sum(
        1 for kw in _STRATEGY_KEYWORDS if kw in lower
    )
    word_count = len(re.findall(r"\b\w+\b", prompt))
    structured_chars = sum(
        1 for c in prompt if c in "{[(,\"':"
    )
    structured_ratio = (
        (structured_chars / len(prompt)) if prompt else 0.0
    )
    prose_ratio = 1.0 - min(structured_ratio * 6.0, 1.0)
    return {
        "keyword_hits": int(keyword_hits),
        "word_count": int(word_count),
        "structured_ratio": round(structured_ratio, 4),
        "prose_ratio": round(prose_ratio, 4),
    }


def _combine_complexity(components: dict[str, Any]) -> float:
    """Combine the per-component signals into a [0, 1] score.

    - Each strategy-keyword hit contributes 0.25 (capped at 1.0
      after four hits).
    - Long prose prompts (>300 words AND prose_ratio > 0.7) get
      a +0.4 bump.
    - Short structured prompts stay near 0.
    """
    keyword_score = min(1.0, components["keyword_hits"] * 0.25)
    word_count = components["word_count"]
    prose_ratio = components["prose_ratio"]
    length_score = 0.0
    if word_count > 300 and prose_ratio > 0.7:
        length_score = 0.4
    elif word_count > 800:
        length_score = 0.6
    combined = max(keyword_score, length_score)
    if components["keyword_hits"] >= 1 and word_count > 100:
        combined = min(1.0, combined + 0.15)
    return round(max(0.0, min(1.0, combined)), 4)


# ── Module-level convenience ────────────────────────────────


_SINGLETON: ModelRouter | None = None
_SINGLETON_LOCK = threading.Lock()


def _get_singleton() -> ModelRouter:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = ModelRouter()
        return _SINGLETON


def classify(
    prompt: str,
    *,
    hint: ModelHint = ModelHint.AUTO,
    purpose: str | None = None,
) -> RoutingDecision:
    """Module-level convenience over the process-wide router
    singleton."""
    return _get_singleton().classify(
        prompt, hint=hint, purpose=purpose,
    )


def route(prompt: str, **kwargs) -> RoutingDecision:
    """Alias for :func:`classify` -- more readable at call sites
    that just want "route this prompt"."""
    return classify(prompt, **kwargs)


def reset_singleton() -> None:
    """Test helper: drop the cached singleton."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON._conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "model_router singleton close raised: %s", exc,
                )
        _SINGLETON = None
