"""Sixth batch: external adapter capabilities.

The first five batches were all ShopAI-native -- engines,
orchestrators, audits living inside the codebase. This batch
registers the EXTERNAL adapters that already exist under
``core/adapters/{llm,sourcing,ads}/``: LLM providers
(Ollama, Gemini, OpenAI-compatible Groq/DeepSeek/Mistral/
OpenRouter), supplier APIs (CJ Dropshipping), and ad
platforms (Meta Ads).

These adapters were built earlier in the project but had no
representation in the capability registry. Operators (and
Claude during a task) querying for "supplier" or "ads"
previously only got internal engines. Now they also get the
real external-tool adapters.

Each registration:
  - kind=adapter
  - module_path points at the adapter class
  - inputs schema describes the friendly call shape
  - scopes_used + side_effects describe what the external
    call DOES
  - tags include "external" so the planner can filter

The router (``core/adapters/router.py``) does the actual
dispatch when an engine invokes a Capability; the registry
entries here are for DISCOVERABILITY via the planner /
operator surface.
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    register_capability,
)


def register_all() -> None:
    """Idempotent batch registration of external adapters."""

    # ── LLM adapters ──────────────────────────────────────

    register_capability(Capability(
        name="ollama_llm",
        kind=CapabilityKind.ADAPTER,
        description=(
            "Local Ollama LLM adapter. Runs Mistral / Qwen "
            "/ Llama / any pulled model via the local "
            "Ollama server at localhost:11434."
        ),
        when_to_use=(
            "Use for offline / privacy-sensitive LLM calls. "
            "Default first choice when prompt complexity is "
            "low (model_router classifies LOCAL tier)."
        ),
        module_path="core.adapters.llm.ollama:OllamaAdapter",
        inputs={
            "messages": "list[{role, content}]",
            "model": "str (qwen2.5 / llama3 / mistral / ...)",
            "temperature": "float (0.0-2.0)",
            "max_tokens": "int",
        },
        outputs={
            "text": "str (generated completion)",
            "tokens_used": "int",
        },
        side_effects=[
            "calls localhost:11434 -- no network egress",
        ],
        tags=["external", "llm", "local", "ollama"],
    ))

    register_capability(Capability(
        name="gemini_llm",
        kind=CapabilityKind.ADAPTER,
        description=(
            "Google Gemini LLM adapter via Generative AI "
            "API."
        ),
        when_to_use=(
            "Use when the task needs cloud LLM with deep "
            "reasoning, long context, or vision. Requires "
            "GEMINI_API_KEY env var."
        ),
        module_path="core.adapters.llm.gemini:GeminiAdapter",
        inputs={
            "messages": "list[{role, content}]",
            "model": "gemini-1.5-flash | gemini-1.5-pro | ...",
        },
        outputs={"text": "str", "tokens_used": "int"},
        side_effects=[
            "egress to generativelanguage.googleapis.com",
            "billable -- token usage tracked by model_router",
        ],
        tags=["external", "llm", "cloud", "gemini",
              "google"],
    ))

    register_capability(Capability(
        name="groq_llm",
        kind=CapabilityKind.ADAPTER,
        description=(
            "Groq LPU-accelerated LLM adapter. "
            "OpenAI-compatible API."
        ),
        when_to_use=(
            "Use when the task needs the lowest possible "
            "LLM latency. Requires GROQ_API_KEY."
        ),
        module_path="core.adapters.llm.groq:GroqAdapter",
        side_effects=[
            "egress to api.groq.com",
            "billable",
        ],
        tags=["external", "llm", "cloud", "groq",
              "low-latency"],
    ))

    register_capability(Capability(
        name="deepseek_llm",
        kind=CapabilityKind.ADAPTER,
        description=(
            "DeepSeek LLM adapter (OpenAI-compatible). "
            "Strong on reasoning + code."
        ),
        when_to_use=(
            "Use when reasoning / code generation is the "
            "primary task. Requires DEEPSEEK_API_KEY."
        ),
        module_path=(
            "core.adapters.llm.deepseek:DeepSeekAdapter"
        ),
        side_effects=[
            "egress to api.deepseek.com",
            "billable",
        ],
        tags=["external", "llm", "cloud", "deepseek",
              "reasoning"],
    ))

    register_capability(Capability(
        name="mistral_llm_cloud",
        kind=CapabilityKind.ADAPTER,
        description=(
            "Mistral La Plateforme cloud LLM adapter."
        ),
        when_to_use=(
            "Use for European-hosted cloud LLM "
            "(data-locality requirements). Requires "
            "MISTRAL_API_KEY."
        ),
        module_path=(
            "core.adapters.llm.mistral:MistralAdapter"
        ),
        side_effects=[
            "egress to api.mistral.ai",
            "billable",
        ],
        tags=["external", "llm", "cloud", "mistral",
              "europe"],
    ))

    register_capability(Capability(
        name="openrouter_llm",
        kind=CapabilityKind.ADAPTER,
        description=(
            "OpenRouter LLM adapter -- access to 100+ "
            "models behind a unified API."
        ),
        when_to_use=(
            "Use when the task needs model-flexibility "
            "without managing N separate vendor keys. "
            "Requires OPENROUTER_API_KEY."
        ),
        module_path=(
            "core.adapters.llm.openrouter:OpenRouterAdapter"
        ),
        side_effects=[
            "egress to openrouter.ai",
            "billable -- per-model pricing",
        ],
        tags=["external", "llm", "cloud", "openrouter",
              "multi-model"],
    ))

    register_capability(Capability(
        name="huggingface_llm",
        kind=CapabilityKind.ADAPTER,
        description=(
            "Hugging Face Inference API LLM adapter."
        ),
        when_to_use=(
            "Use for open-source models hosted on HF "
            "Inference. Requires HUGGINGFACE_API_KEY."
        ),
        module_path=(
            "core.adapters.llm.huggingface:"
            "HuggingFaceAdapter"
        ),
        side_effects=[
            "egress to api-inference.huggingface.co",
        ],
        tags=["external", "llm", "cloud", "huggingface",
              "open-source"],
    ))

    # ── Sourcing / supplier adapters ──────────────────────

    register_capability(Capability(
        name="cj_dropshipping",
        kind=CapabilityKind.ADAPTER,
        description=(
            "CJ Dropshipping supplier adapter. Search "
            "products, place orders, track fulfilment."
        ),
        when_to_use=(
            "Use when the goal involves dropshipping "
            "sourcing -- searching the CJ catalog, placing "
            "fulfilment orders, or tracking supplier "
            "shipping status. Requires CJ_DROPSHIPPING_API_KEY."
        ),
        module_path=(
            "core.adapters.sourcing.cj_dropshipping:"
            "CJDropshippingAdapter"
        ),
        inputs={
            "query": "str (search phrase)",
            "category": "str (optional)",
            "page": "int",
        },
        outputs={
            "products": "list of supplier product dicts",
            "total_count": "int",
        },
        side_effects=[
            "egress to developers.cjdropshipping.com",
            "API quota consumed per call",
        ],
        composes_with=["supplier_discovery", "supplier"],
        tags=["external", "sourcing", "supplier",
              "dropshipping", "cj"],
    ))

    # ── Ads platform adapters ─────────────────────────────

    register_capability(Capability(
        name="meta_ads",
        kind=CapabilityKind.ADAPTER,
        description=(
            "Meta (Facebook / Instagram) Ads platform "
            "adapter. Create / pause / update campaigns + "
            "read performance metrics."
        ),
        when_to_use=(
            "Use when the goal involves Meta ads -- "
            "launching campaigns, adjusting budgets, "
            "pulling ROAS reports. Requires "
            "META_ADS_ACCESS_TOKEN."
        ),
        module_path=(
            "core.adapters.ads.meta_ads:MetaAdsAdapter"
        ),
        inputs={
            "account_id": "str (Meta ad account)",
            "campaign_name": "str",
            "daily_budget": "float (USD)",
            "objective": "str (CONVERSIONS / TRAFFIC / ...)",
        },
        outputs={
            "campaign_id": "str",
            "performance": "dict (spend / clicks / "
                          "conversions)",
        },
        side_effects=[
            "egress to graph.facebook.com",
            "billable ad spend when campaigns run",
        ],
        composes_with=["ad_creative_generator",
                       "audience_targeting",
                       "campaign_strategy"],
        scopes_used=["ads_management", "ads_read"],
        tags=["external", "ads", "meta", "facebook",
              "instagram"],
    ))


# Note: ``shopai capabilities list --tag external`` after
# bootstrap shows the full external surface. The planner can
# now route queries like "find new dropshipping suppliers" ->
# cj_dropshipping + supplier_discovery, or "launch Meta ad
# campaign" -> meta_ads + ad_creative_generator.
