"""LLMAdapter — unified interface for all AI models.

System never calls models directly. Always through adapter.
Supports: Ollama (Mistral/Qwen/LLaMA), OpenAI, Anthropic, any future model.

Usage:
    llm = get_llm()
    result = llm.ask("analyzer", "What price should this product be?", context={...})
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from utils.logger import get_logger

logger = get_logger("llm_adapter")


class LLMConfig:
    """Configuration for an LLM provider."""

    def __init__(self, provider: str, model: str, url: str = "",
                 api_key: str = "", max_tokens: int = 800,
                 temperature: float = 0.3, timeout: int = 300) -> None:
        self.provider = provider  # "ollama", "openai", "anthropic"
        self.model = model
        self.url = url
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout


class LLMResponse:
    """Standardized response from any LLM."""

    def __init__(self, text: str, model: str, provider: str,
                 tokens_used: int = 0, duration_s: float = 0,
                 success: bool = True, error: str = "") -> None:
        self.text = text
        self.model = model
        self.provider = provider
        self.tokens_used = tokens_used
        self.duration_s = duration_s
        self.success = success
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "model": self.model, "provider": self.provider,
            "tokens_used": self.tokens_used, "duration_s": self.duration_s,
            "success": self.success, "error": self.error,
        }

    def parse_json(self) -> dict[str, Any]:
        """Try to parse JSON from response text."""
        try:
            start = self.text.find("{")
            end = self.text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(self.text[start:end])
        except json.JSONDecodeError:
            pass
        return {"raw": self.text}


class LLMAdapter:
    """Unified interface for all AI models."""

    # Role → model mapping (configurable)
    DEFAULT_ROLES = {
        "analyzer": "mistral",      # Analysis, evaluation, decisions
        "worker": "qwen2.5",        # Data processing, calculations
        "creative": "llama3.2",     # Content generation, descriptions
        "validator": "mistral",      # Quality checks
        "general": "mistral",        # Default
    }

    def __init__(self) -> None:
        self._configs: dict[str, LLMConfig] = {}
        self._role_map: dict[str, str] = dict(self.DEFAULT_ROLES)
        self._stats: dict[str, dict[str, Any]] = {}
        self._available_models: list[str] = []
        self._checked = False

    # ── Configuration ────────────────────────────────────────

    def add_provider(self, name: str, config: LLMConfig) -> None:
        """Register an LLM provider."""
        self._configs[name] = config

    def set_role_model(self, role: str, model: str) -> None:
        """Override which model handles a role."""
        self._role_map[role] = model

    def auto_configure(self) -> dict[str, Any]:
        """Auto-detect and configure available models."""
        configured = []

        # Ollama (local, free)
        ollama_url = os.environ.get("SHOPAI_OLLAMA_URL", "http://localhost:11434")
        try:
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
                self._available_models = models
                for model in models:
                    self._configs[model] = LLMConfig(
                        provider="ollama", model=model, url=ollama_url,
                    )
                    configured.append(f"ollama:{model}")
        except Exception:
            pass

        # OpenAI (if API key set)
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            self._configs["gpt-4"] = LLMConfig(
                provider="openai", model="gpt-4o",
                url="https://api.openai.com/v1/chat/completions",
                api_key=openai_key,
            )
            configured.append("openai:gpt-4o")

        # Anthropic (if API key set)
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            self._configs["claude"] = LLMConfig(
                provider="anthropic", model="claude-sonnet-4-6",
                url="https://api.anthropic.com/v1/messages",
                api_key=anthropic_key,
            )
            configured.append("anthropic:claude-sonnet-4-6")

        # Update role mapping based on available models
        if "mistral" in self._available_models:
            self._role_map["analyzer"] = "mistral"
            self._role_map["validator"] = "mistral"
        if any("qwen" in m for m in self._available_models):
            qwen = next(m for m in self._available_models if "qwen" in m)
            self._role_map["worker"] = qwen
        if any("llama" in m for m in self._available_models):
            llama = next(m for m in self._available_models if "llama" in m)
            self._role_map["creative"] = llama

        self._checked = True
        return {"configured": configured, "roles": dict(self._role_map)}

    # ── Main Interface ───────────────────────────────────────

    def ask(self, role: str, prompt: str, context: dict | None = None,
            system_prompt: str = "") -> LLMResponse:
        """Ask an LLM with role-based routing."""
        if not self._checked:
            self.auto_configure()

        model_name = self._role_map.get(role, self._role_map.get("general", "mistral"))
        config = self._configs.get(model_name)

        if not config:
            # Try any available model
            if self._configs:
                model_name = next(iter(self._configs))
                config = self._configs[model_name]
            else:
                return LLMResponse("", model_name, "none", success=False,
                                  error="No LLM configured")

        # Add context to prompt
        full_prompt = prompt
        if context:
            ctx_str = json.dumps(context, default=str)[:2000]
            full_prompt = f"{prompt}\n\nContext: {ctx_str}"

        start = time.monotonic()
        try:
            if config.provider == "ollama":
                response = self._call_ollama(config, full_prompt, system_prompt)
            elif config.provider == "openai":
                response = self._call_openai(config, full_prompt, system_prompt)
            elif config.provider == "anthropic":
                response = self._call_anthropic(config, full_prompt, system_prompt)
            else:
                return LLMResponse("", model_name, config.provider, success=False,
                                  error=f"Unknown provider: {config.provider}")

            response.duration_s = round(time.monotonic() - start, 2)
            self._record_stats(model_name, response)
            return response

        except Exception as exc:
            elapsed = round(time.monotonic() - start, 2)
            return LLMResponse("", model_name, config.provider if config else "?",
                             duration_s=elapsed, success=False, error=str(exc))

    def ask_json(self, role: str, prompt: str, context: dict | None = None) -> dict[str, Any]:
        """Ask and parse JSON response."""
        response = self.ask(role, prompt, context)
        if not response.success:
            return {"error": response.error}
        return response.parse_json()

    # ── Provider Implementations ─────────────────────────────

    def _call_ollama(self, config: LLMConfig, prompt: str,
                     system_prompt: str = "") -> LLMResponse:
        payload: dict[str, Any] = {
            "model": config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": config.temperature,
                "num_predict": config.max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{config.url}/api/generate", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            result = json.loads(resp.read())

        return LLMResponse(
            text=result.get("response", ""),
            model=config.model, provider="ollama",
            tokens_used=result.get("eval_count", 0),
        )

    def _call_openai(self, config: LLMConfig, prompt: str,
                     system_prompt: str = "") -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }).encode()

        req = urllib.request.Request(
            config.url, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            result = json.loads(resp.read())

        choice = result.get("choices", [{}])[0]
        return LLMResponse(
            text=choice.get("message", {}).get("content", ""),
            model=config.model, provider="openai",
            tokens_used=result.get("usage", {}).get("total_tokens", 0),
        )

    def _call_anthropic(self, config: LLMConfig, prompt: str,
                        system_prompt: str = "") -> LLMResponse:
        payload: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            config.url, data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            result = json.loads(resp.read())

        content = result.get("content", [{}])[0]
        return LLMResponse(
            text=content.get("text", ""),
            model=config.model, provider="anthropic",
            tokens_used=result.get("usage", {}).get("input_tokens", 0) +
                        result.get("usage", {}).get("output_tokens", 0),
        )

    # ── Stats ────────────────────────────────────────────────

    def _record_stats(self, model: str, response: LLMResponse) -> None:
        if model not in self._stats:
            self._stats[model] = {"calls": 0, "tokens": 0, "errors": 0, "total_time": 0}
        s = self._stats[model]
        s["calls"] += 1
        s["tokens"] += response.tokens_used
        s["total_time"] += response.duration_s
        if not response.success:
            s["errors"] += 1

    def get_stats(self) -> dict[str, Any]:
        return {
            "models": dict(self._stats),
            "available": self._available_models,
            "roles": dict(self._role_map),
        }

    def get_available_models(self) -> list[str]:
        if not self._checked:
            self.auto_configure()
        return list(self._available_models)


# Singleton
_llm: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _llm
    if _llm is None:
        _llm = LLMAdapter()
        _llm.auto_configure()
    return _llm
