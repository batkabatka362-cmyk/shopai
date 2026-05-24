"""AI-based strategy plug-ins for Tier 1 + Tier 2b.

Substrate-first proof: AICaptainStrategy + AIOrchestratorStrategy
plug into the existing protocols without disturbing any other
layer. When models improve, the system improves. When models
are unavailable, the deterministic strategies still run.

## Design

LLM is a CONSULTANT, not the foundation. Two-stage:

  1. Deterministic strategy runs FIRST + emits its plan
  2. LLM is asked to REVIEW or REFINE the plan given memory +
     signals
  3. LLM response is parsed; failure -> fall back to
     deterministic plan UNCHANGED
  4. Operator can disable AI strategy via env var
     (SHOPAI_AI_STRATEGY=0) -- system stays autonomous

This respects the user's framing: model-driven agent would
be brittle; substrate-driven with AI consultant on top is
robust.

## Env vars

  SHOPAI_AI_STRATEGY=1            enable AI strategies
  SHOPAI_AI_STRATEGY_MODEL=...    optional model identifier
                                  (default: gpt-4o-mini or
                                  whatever the local LLM
                                  shim provides)
  SHOPAI_AI_STRATEGY_TIMEOUT=15   seconds to wait for LLM

## Strategies

  AICaptainStrategy:
    - Inherits SignalDrivenCaptainStrategy as base
    - Asks LLM "given these signals + cluster memory verdict,
      which of these members should fire?"
    - Parses LLM response (JSON list of engine names)
    - Validates: subset of wired_members
    - Falls back to deterministic if LLM fails / disabled

  AIOrchestratorStrategy:
    - Inherits DeterministicOrchestratorStrategy
    - Asks LLM "given this store's world-model, what priority
      class fits best?"
    - Parses LLM response (one of: launching/growing/mature/
      at_risk/stagnant)
    - Falls back to deterministic
"""
from __future__ import annotations

import json
import os
from typing import Any

from engines._cluster_captain import (
    SignalDrivenCaptainStrategy,
)
from engines._clusters import Cluster
from engines._orchestrator import (
    DeterministicOrchestratorStrategy,
    StorePriority,
    _PRIORITY_CLUSTERS,
)


def _ai_enabled() -> bool:
    """Env-var gate. AI strategies are opt-in."""
    return bool(os.environ.get("SHOPAI_AI_STRATEGY"))


class _LLMClient:
    """Minimal LLM client shim. Looks for openai package +
    OPENAI_API_KEY; otherwise reports unavailable.

    Real ShopAI deployment would plug in whatever model
    backend the operator configures (Anthropic, local Ollama,
    Bedrock, etc.). For this prototype, openai is the default.
    """

    def __init__(self) -> None:
        self._client = None
        self._model = os.environ.get(
            "SHOPAI_AI_STRATEGY_MODEL", "gpt-4o-mini",
        )
        self._timeout = float(
            os.environ.get(
                "SHOPAI_AI_STRATEGY_TIMEOUT", "15"
            ) or "15"
        )

    @property
    def available(self) -> bool:
        return self._load() is not None

    def _load(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai  # noqa: F401
        except ImportError:
            return None
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        try:
            from openai import OpenAI
            self._client = OpenAI(timeout=self._timeout)
        except Exception:  # noqa: BLE001
            return None
        return self._client

    def chat_json(
        self, system: str, user: str,
    ) -> dict[str, Any] | None:
        """Ask LLM to return JSON. None on any failure."""
        client = self._load()
        if client is None:
            return None
        try:
            resp = client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = resp.choices[0].message.content or "{}"
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:  # noqa: BLE001
            return None


class AICaptainStrategy:
    """LLM-consulted captain. Base is SignalDriven; LLM may
    refine the selection but never CONTRADICT risk gates."""

    def __init__(self, llm: _LLMClient | None = None) -> None:
        self._base = SignalDrivenCaptainStrategy()
        self._llm = llm or _LLMClient()

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        base = self._base.select_members(
            cluster, wired_members, signals,
        )
        if not _ai_enabled():
            return base
        if not self._llm.available:
            return base

        # Build cluster memory context
        memory_summary = ""
        try:
            from engines._cluster_memory import (
                cluster_health_rollup,
            )
            h = cluster_health_rollup(cluster.name)
            if h is not None:
                memory_summary = (
                    f"Cluster health: {h.health_verdict} "
                    f"(success_rate={h.success_rate}, "
                    f"executed={h.total_executed}, "
                    f"revenue=${h.total_revenue:.2f})"
                )
        except Exception:  # noqa: BLE001
            pass

        system = (
            "You are a Tier 2b cluster captain for ShopAI -- "
            "an autonomous Shopify merchant. Given cluster "
            "definition + signals + recent memory, recommend "
            "which member engines to fire THIS cycle. Return "
            "JSON: {\"fire\": [\"engine_name\", ...], "
            "\"rationale\": \"...\"}. Only return engines "
            "from the wired_members list. The deterministic "
            "baseline already selected some engines -- you "
            "may REFINE (drop / add / keep) but cannot pick "
            "engines outside wired_members."
        )
        user = json.dumps({
            "cluster": cluster.name,
            "kpi": cluster.kpi,
            "description": cluster.description,
            "signals": signals,
            "wired_members": wired_members,
            "deterministic_selection": base,
            "memory_summary": memory_summary,
        })

        resp = self._llm.chat_json(system, user)
        if resp is None:
            return base
        ai_fire = resp.get("fire")
        if not isinstance(ai_fire, list):
            return base

        # Validate: must be subset of wired_members
        wired_set = set(wired_members)
        validated = [e for e in ai_fire if e in wired_set]
        if not validated:
            # Defensive: LLM returned empty / all-invalid ->
            # fall back to base rather than firing nothing
            return base
        return validated


class AIOrchestratorStrategy:
    """LLM-consulted Tier 1 priority assignment. Base is
    deterministic; LLM may RECLASSIFY a store within the
    known priority set."""

    _VALID_PRIORITIES = frozenset({
        "launching", "growing", "mature", "at_risk", "stagnant",
    })

    def __init__(self, llm: _LLMClient | None = None) -> None:
        self._base = DeterministicOrchestratorStrategy()
        self._llm = llm or _LLMClient()

    def decide_priority(
        self, store_id: str, world_model: dict[str, Any],
    ) -> StorePriority:
        base = self._base.decide_priority(store_id, world_model)
        if not _ai_enabled():
            return base
        if not self._llm.available:
            return base

        system = (
            "You are a Tier 1 orchestrator for ShopAI -- an "
            "autonomous Shopify merchant empire. Given a "
            "store's world-model, classify the store's "
            "current priority. Return JSON: "
            "{\"priority\": \"launching|growing|mature|"
            "at_risk|stagnant\", \"rationale\": \"...\"}. "
            "Deterministic baseline already gave one answer; "
            "you may agree or refine, but only pick from the "
            "five known classes."
        )
        user = json.dumps({
            "store_id": store_id,
            "world_model_stats": world_model.get("stats", {}),
            "deterministic_classification": {
                "priority": base.priority,
                "rationale": base.rationale,
            },
        })

        resp = self._llm.chat_json(system, user)
        if resp is None:
            return base
        ai_priority = resp.get("priority")
        if ai_priority not in self._VALID_PRIORITIES:
            return base

        # Re-build the StorePriority with the AI's class
        return StorePriority(
            store_id=store_id,
            priority=ai_priority,
            cluster_focus=_PRIORITY_CLUSTERS.get(
                ai_priority, _PRIORITY_CLUSTERS["default"],
            ),
            rationale=(
                f"[AI] {resp.get('rationale', 'no rationale')} "
                f"(deterministic baseline: {base.priority})"
            ),
            signals=base.signals,
        )
