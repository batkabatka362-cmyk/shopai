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

        # Wave 17: feed attribution context to the LLM so it
        # can reason about ROI ("loyalty earned $5k, churn_pred
        # earned $50 -- prefer loyalty even if both signals
        # match"). Per-engine attribution scoped to this
        # cluster's members.
        attribution_context = self._attribution_context(
            cluster, wired_members,
        )

        # Wave 75: niche signal (orchestrator threads it
        # through ``signals["niche"]``). Captain LLM uses it
        # to bias selection (e.g. beauty store retention -->
        # loyalty matters more than nps_engine).
        niche = (signals or {}).get("niche")
        if isinstance(niche, str):
            niche = niche.strip().lower() or None
        else:
            niche = None

        system = (
            "You are a Tier 2b cluster captain for ShopAI -- "
            "an autonomous Shopify merchant. Given cluster "
            "definition + signals + recent memory + per-engine "
            "revenue attribution (with trend) + store niche, "
            "recommend which member engines to fire THIS cycle. "
            "Return JSON: {\"fire\": [\"engine_name\", ...], "
            "\"rationale\": \"...\"}. Only return engines "
            "from the wired_members list. The deterministic "
            "baseline already selected some engines -- you "
            "may REFINE (drop / add / keep) but cannot pick "
            "engines outside wired_members. Engines with "
            "higher recent revenue attribution generally "
            "deserve priority. Engines with trend='rising' "
            "deserve continued investment; trend='falling' "
            "deserves caution (maybe deprioritize unless a "
            "signal explicitly calls for it). Niche affects "
            "engine preference -- e.g. beauty stores favour "
            "loyalty over generic outreach; tech stores favour "
            "review_management."
        )
        user = json.dumps({
            "cluster": cluster.name,
            "niche": niche,
            "kpi": cluster.kpi,
            "description": cluster.description,
            "signals": signals,
            "wired_members": wired_members,
            "deterministic_selection": base,
            "memory_summary": memory_summary,
            "attribution_7d": attribution_context,
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

    def _attribution_context(
        self,
        cluster: Cluster,
        wired_members: list[str],
    ) -> dict[str, Any]:
        """Build per-member attribution dict for the LLM prompt.

        Returns a compact dict the model can reason over:
            {
              "cluster_attributed_revenue": float,
              "members": [
                {
                  "engine": ..., "revenue": float, "orders": int,
                  "trend": "rising"|"falling"|"flat"|"new",
                  "recent_revenue": [old -> new floats],
                },
                ...
              ],
              "top_engine": str | None,
            }

        Empty values when no attribution data is available --
        the model still works without the signal, just less
        informed.
        """
        out: dict[str, Any] = {
            "cluster_attributed_revenue": 0.0,
            "members": [],
            "top_engine": None,
        }
        try:
            from engines._revenue_attribution import attribute_revenue
            report = attribute_revenue(window_hours=168.0)
        except Exception:  # noqa: BLE001
            return out

        wired_set = set(wired_members)
        # Cluster-level revenue
        for c in report.per_cluster:
            if c.cluster == cluster.name:
                out["cluster_attributed_revenue"] = round(
                    c.attributed_revenue, 2,
                )
                break

        # Per-engine revenue + Wave 34 trend (last 3 snapshots)
        try:
            from engines._attribution_snapshot import (
                engine_revenue_history,
            )
        except Exception:  # noqa: BLE001
            engine_revenue_history = None

        members: list[dict[str, Any]] = []
        for e in report.per_engine:
            if e.engine not in wired_set:
                continue
            member = {
                "engine": e.engine,
                "revenue": round(e.attributed_revenue, 2),
                "orders": e.attributed_orders,
                "trend": "new",
                "recent_revenue": [],
            }
            if engine_revenue_history is not None:
                try:
                    history = engine_revenue_history(
                        e.engine, limit=3,
                    )
                except Exception:  # noqa: BLE001
                    history = []
                if history:
                    member["recent_revenue"] = [
                        round(h["attributed_revenue"], 2)
                        for h in history
                    ]
                    if len(history) >= 2:
                        old = history[0]["attributed_revenue"]
                        new = history[-1]["attributed_revenue"]
                        if new > old * 1.1:
                            member["trend"] = "rising"
                        elif new < old * 0.9:
                            member["trend"] = "falling"
                        else:
                            member["trend"] = "flat"
                    else:
                        member["trend"] = "new"
            members.append(member)
        out["members"] = members
        if members:
            out["top_engine"] = members[0]["engine"]
        return out


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

        # Wave 24: per-cluster attribution context for this
        # store. Lets the LLM reason "retention earns $5k here,
        # acquisition earns $50 -- the priority should reflect
        # which clusters are pulling weight".
        attribution_context = self._store_attribution_context(
            store_id,
        )
        # Wave 75: niche signal -- LLM knows beauty vs tech
        # context affects priority bucketing.
        niche = self._store_niche(store_id)

        system = (
            "You are a Tier 1 orchestrator for ShopAI -- an "
            "autonomous Shopify merchant empire. Given a "
            "store's world-model + per-cluster revenue "
            "attribution with trend + niche, classify the "
            "store's current priority. Return JSON: "
            "{\"priority\": \"launching|growing|mature|"
            "at_risk|stagnant\", \"rationale\": \"...\"}. "
            "Deterministic baseline already gave one answer; "
            "you may agree or refine, but only pick from the "
            "five known classes. Stores earning meaningfully "
            "tend toward mature/growing; stores with $0 "
            "attribution toward launching/at_risk. Stores "
            "with mostly trend='falling' clusters lean toward "
            "at_risk/stagnant even if current revenue looks OK. "
            "Niche affects pacing -- beauty/fashion stores "
            "ramp faster than tech/home (shorter sales cycle)."
        )
        user = json.dumps({
            "store_id": store_id,
            "niche": niche,
            "world_model_stats": world_model.get("stats", {}),
            "attribution_7d": attribution_context,
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

    def _store_niche(self, store_id: str) -> str | None:
        """Wave 75: look up the store's niche from
        StoreManager. Returns None for unset / general."""
        try:
            from data_pipeline.store.store_manager import (
                StoreManager,
            )
            store = StoreManager().get_store(store_id) or {}
            niche = (store.get("niche") or "").strip().lower()
            if niche and niche != "general":
                return niche
        except Exception:  # noqa: BLE001
            return None
        return None

    def _store_attribution_context(
        self, store_id: str,
    ) -> dict[str, Any]:
        """Per-store cluster attribution for the LLM prompt.

        Returns dict shape:
            {
              "attributed_revenue": float,
              "total_orders_in_window": int,
              "attribution_rate": float,
              "top_clusters": [
                {
                  "cluster": ..., "revenue": float,
                  "orders": int, "confidence": ...,
                  "trend": "rising"|"falling"|"flat"|"new",
                  "recent_revenue": [...],
                },
                ...
              ],
            }

        Empty values when no attribution data -- LLM still
        works without the signal.
        """
        out: dict[str, Any] = {
            "attributed_revenue": 0.0,
            "total_orders_in_window": 0,
            "attribution_rate": 0.0,
            "top_clusters": [],
        }
        try:
            from engines._revenue_attribution import attribute_revenue
            report = attribute_revenue(
                window_hours=168.0, store_id=store_id,
            )
        except Exception:  # noqa: BLE001
            return out

        # Wave 35: per-cluster trend from snapshot history
        # (symmetric to Wave 34 captain trend on engines).
        try:
            from engines._attribution_snapshot import (
                cluster_revenue_history,
            )
        except Exception:  # noqa: BLE001
            cluster_revenue_history = None

        out["attributed_revenue"] = round(
            report.attributed_revenue, 2,
        )
        out["total_orders_in_window"] = (
            report.total_orders_in_window
        )
        out["attribution_rate"] = report.attribution_rate

        top_clusters: list[dict[str, Any]] = []
        for c in report.per_cluster[:5]:
            entry: dict[str, Any] = {
                "cluster": c.cluster,
                "revenue": round(c.attributed_revenue, 2),
                "orders": c.attributed_orders,
                "confidence": c.confidence,
                "trend": "new",
                "recent_revenue": [],
            }
            if cluster_revenue_history is not None:
                try:
                    history = cluster_revenue_history(
                        c.cluster, limit=3, store_id=store_id,
                    )
                except Exception:  # noqa: BLE001
                    history = []
                if history:
                    entry["recent_revenue"] = [
                        round(h["attributed_revenue"], 2)
                        for h in history
                    ]
                    if len(history) >= 2:
                        old = history[0]["attributed_revenue"]
                        new = history[-1]["attributed_revenue"]
                        if new > old * 1.1:
                            entry["trend"] = "rising"
                        elif new < old * 0.9:
                            entry["trend"] = "falling"
                        else:
                            entry["trend"] = "flat"
            top_clusters.append(entry)
        out["top_clusters"] = top_clusters
        return out
