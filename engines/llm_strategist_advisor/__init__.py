"""LLM Strategist Advisor — W963-51 (Phase 3.B opener).

LLM-augmented pattern surfacing over `strategist_memory`
(W963-43) records. Deterministic baseline ranks recalls by
positive-outcome frequency; LLM may REFINE the ranking with
qualitative pattern insight ("recovery codes work but only
in beauty stores", "high-margin SKUs don't need discounts").

Consultant pattern (Wave 17/24/34/49):
  1. Deterministic baseline ALWAYS runs first.
  2. LLM is OPT-IN via SHOPAI_AI_STRATEGY=1 + OPENAI_API_KEY.
  3. LLM is asked to RANK the existing recommendations + add
     pattern_insight strings. It cannot invent new actions.
  4. LLM response is validated; invalid -> deterministic.

Pattern J guard: short-circuits under pytest (engine + helper).

CLI:
  shopai llm-strategist [--store STORE] [--signal SIG]
                        [--k N] [--json]
"""
from .flow import LlmStrategistAdvisorEngine

__all__ = ["LlmStrategistAdvisorEngine"]
