"""LLM adapter bootstrap.

Single entry point that instantiates every available LLM
adapter and registers it with ``AdapterRegistry``. Call this
once at process startup (or from an admin endpoint) to wire the
brain to the full LLM ecosystem.

Usage::

    from core.adapters.llm.bootstrap import register_all
    register_all()

The bootstrap is idempotent — calling it twice is safe (uses
``replace=True`` so second-call adapter instances overwrite the
first). Adapters whose API key is unset still register; the
router will simply skip them via ``is_configured()``.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .anthropic import AnthropicAdapter
from .deepseek import DeepSeekAdapter
from .gemini import GeminiAdapter
from .groq import GroqAdapter
from .huggingface import HuggingFaceAdapter
from .mistral import MistralAdapter
from .ollama import OllamaAdapter
from .openai import OpenAIAdapter
from .openrouter import OpenRouterAdapter

logger = get_logger("adapters.llm.bootstrap")


_LLM_ADAPTER_CLASSES = (
    GroqAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    DeepSeekAdapter,
    MistralAdapter,
    OllamaAdapter,
    OpenRouterAdapter,
    HuggingFaceAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every LLM adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map so the
    caller can log how many adapters are actually wired up
    (instead of merely registered).
    """
    reg = registry if registry is not None else get_registry()
    status: dict[str, bool] = {}

    for cls in _LLM_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s", cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s", adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "LLM adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status


def configured_count(registry: AdapterRegistry | None = None) -> int:
    """Return how many LLM adapters currently have credentials
    set in the environment."""
    reg = registry if registry is not None else get_registry()
    return sum(
        1 for a in reg.find_by_category("llm") if a.is_configured()
    )
