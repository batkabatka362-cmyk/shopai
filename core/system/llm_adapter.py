"""LLMAdapter — unified, production-grade interface for all AI models.

ShopAI never calls models directly. Every cognitive module, every
intelligence helper, every decision routine flows through this
adapter. The adapter handles:

    - Local Ollama (Mistral, Qwen, LLaMA family)
    - OpenAI Chat Completions API
    - Anthropic Messages API
    - Auto-detection of available providers
    - Retry with exponential backoff on transient failures
    - Provider fallback chain (e.g. local → OpenAI → Anthropic)
    - JSON-mode + structured output parsing
    - Per-call statistics + token accounting
    - Role-based model routing (analyzer, worker, creative, …)

Usage:

    llm = get_llm()
    resp = llm.ask("analyzer", "What price should this product be?",
                   context={"price": 25, "cost": 10})
    if resp.success:
        print(resp.text)

    # Structured output:
    parsed = llm.ask_structured("analyzer", prompt, schema={...})
    if parsed.ok:
        print(parsed.data)

The adapter is fully usable with NO providers configured — every
method returns a structured failure result so callers can fall
back to heuristics. This is the design contract: the system runs
to completion even with zero LLMs available, and gets richer when
they're online.
"""
from __future__ import annotations

import json
import os
import threading as _threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("llm_adapter")


# ── Defaults ──────────────────────────────────────────────────

# Modern model defaults (2026). Override via env vars or set_role_model.
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Cheap-but-good model defaults — easy to override
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

DEFAULT_MAX_TOKENS = 800
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TIMEOUT = 60
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 0.5  # seconds; doubles each retry


# ── Dataclasses ───────────────────────────────────────────────


@dataclass
class LLMConfig:
    """Configuration for one LLM provider."""
    provider: str  # "ollama" | "openai" | "anthropic"
    model: str
    url: str = ""
    api_key: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    timeout: int = DEFAULT_TIMEOUT
    supports_json_mode: bool = False  # OpenAI/Anthropic structured output


@dataclass
class LLMResponse:
    """Standardized response from any LLM call."""
    text: str = ""
    model: str = ""
    provider: str = ""
    tokens_used: int = 0
    duration_s: float = 0.0
    success: bool = True
    error: str = ""
    attempts: int = 1
    fallback_used: bool = False  # True if a non-preferred provider answered

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "tokens_used": self.tokens_used,
            "duration_s": round(self.duration_s, 3),
            "success": self.success,
            "error": self.error,
            "attempts": self.attempts,
            "fallback_used": self.fallback_used,
        }

    def parse_json(self) -> dict[str, Any]:
        """Best-effort JSON parse. Tolerant of code fences and chatter.

        Returns the parsed dict, or {"raw": <text>} if parsing failed.
        Use ``ask_structured()`` for stricter handling.
        """
        if not self.text:
            return {"raw": ""}
        text = self.text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        # Find first {…}
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if 0 <= start < end:
                return json.loads(text[start:end])
        except json.JSONDecodeError as exc:
            logger.debug("LLM response JSON parse failed: %s", exc)
        return {"raw": self.text}


@dataclass
class StructuredResponse:
    """Result of `ask_structured()` — strict JSON parsing with status."""
    ok: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    error: str = ""
    response: Optional[LLMResponse] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "raw_text": self.raw_text,
            "error": self.error,
        }


# ── Adapter ───────────────────────────────────────────────────


class LLMAdapter:
    """Unified production-grade interface for all AI models."""

    # Role → preferred model name. Auto-configure may override.
    DEFAULT_ROLES: dict[str, str] = {
        "analyzer":  "mistral",       # analysis, evaluation, decisions
        "worker":    "qwen2.5",       # data processing, calculations
        "creative":  "llama3.2",      # content generation, descriptions
        "validator": "mistral",       # quality checks
        "reasoner":  "mistral",       # multi-step reasoning, planning
        "general":   "mistral",
    }

    # Order to try when the role's preferred model is unavailable.
    # First entries are local + cheap; last are expensive remote.
    DEFAULT_FALLBACK_CHAIN: list[str] = ["mistral", "qwen2.5", "llama3.2"]

    def __init__(self) -> None:
        self._configs: dict[str, LLMConfig] = {}
        self._role_map: dict[str, str] = dict(self.DEFAULT_ROLES)
        self._fallback_chain: list[str] = list(self.DEFAULT_FALLBACK_CHAIN)
        self._stats: dict[str, dict[str, Any]] = {}
        self._available_models: list[str] = []
        self._checked = False
        self._retry_attempts = DEFAULT_RETRY_ATTEMPTS
        self._retry_base_delay = DEFAULT_RETRY_BASE_DELAY

    # ── Configuration ─────────────────────────────────────────

    def add_provider(self, name: str, config: LLMConfig) -> None:
        """Manually register an LLM provider (for tests / custom setups)."""
        self._configs[name] = config
        if name not in self._fallback_chain:
            self._fallback_chain.append(name)

    def set_role_model(self, role: str, model: str) -> None:
        """Override which model handles a role."""
        self._role_map[role] = model

    def set_fallback_chain(self, chain: list[str]) -> None:
        """Override the order in which models are tried when a role's
        preferred model is unavailable or fails."""
        self._fallback_chain = list(chain)

    def set_retry_policy(self, attempts: int, base_delay: float = 0.5) -> None:
        self._retry_attempts = max(1, int(attempts))
        self._retry_base_delay = max(0.0, float(base_delay))

    def auto_configure(self) -> dict[str, Any]:
        """Auto-detect and register every available LLM provider.

        Probes:
            1. Ollama at $SHOPAI_OLLAMA_URL (default localhost:11434)
            2. OpenAI if $OPENAI_API_KEY is set
            3. Anthropic if $ANTHROPIC_API_KEY is set

        Updates the role map based on which Ollama models are
        actually present so the system always picks the right
        local model where one exists.
        """
        configured: list[str] = []

        # ── Ollama (local, free) ──
        ollama_url = os.environ.get("SHOPAI_OLLAMA_URL", DEFAULT_OLLAMA_URL)
        try:
            req = urllib.request.Request(
                f"{ollama_url}/api/tags", method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "").split(":")[0]
                          for m in data.get("models", [])]
                self._available_models = [m for m in models if m]
                for model in self._available_models:
                    if model not in self._configs:
                        self._configs[model] = LLMConfig(
                            provider="ollama", model=model, url=ollama_url,
                        )
                        configured.append(f"ollama:{model}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ollama auto-detect: %s", exc)

        # ── OpenAI ──
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        openai_model = os.environ.get(
            "SHOPAI_OPENAI_MODEL", DEFAULT_OPENAI_MODEL,
        )
        if openai_key:
            self._configs["openai"] = LLMConfig(
                provider="openai", model=openai_model,
                url=DEFAULT_OPENAI_URL, api_key=openai_key,
                supports_json_mode=True,
            )
            if "openai" not in self._fallback_chain:
                self._fallback_chain.append("openai")
            configured.append(f"openai:{openai_model}")

        # ── Anthropic ──
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        anthropic_model = os.environ.get(
            "SHOPAI_ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL,
        )
        if anthropic_key:
            self._configs["anthropic"] = LLMConfig(
                provider="anthropic", model=anthropic_model,
                url=DEFAULT_ANTHROPIC_URL, api_key=anthropic_key,
                supports_json_mode=True,
            )
            if "anthropic" not in self._fallback_chain:
                self._fallback_chain.append("anthropic")
            configured.append(f"anthropic:{anthropic_model}")

        # ── Update role map from actually-available local models ──
        if "mistral" in self._available_models:
            self._role_map["analyzer"] = "mistral"
            self._role_map["validator"] = "mistral"
            self._role_map["reasoner"] = "mistral"
            self._role_map["general"] = "mistral"
        if any("qwen" in m for m in self._available_models):
            qwen = next(m for m in self._available_models if "qwen" in m)
            self._role_map["worker"] = qwen
        if any("llama" in m for m in self._available_models):
            llama = next(m for m in self._available_models if "llama" in m)
            self._role_map["creative"] = llama

        self._checked = True
        logger.info(
            "LLM auto-configured: %d providers (%s)",
            len(configured), ", ".join(configured) or "none",
        )
        return {
            "configured": configured,
            "roles": dict(self._role_map),
            "fallback_chain": list(self._fallback_chain),
            "available_local": list(self._available_models),
        }

    def is_available(self) -> bool:
        """Return True iff at least one provider is configured."""
        if not self._checked:
            self.auto_configure()
        return bool(self._configs)

    # ── Main interface ────────────────────────────────────────

    def ask(
        self,
        role: str,
        prompt: str,
        context: Optional[dict] = None,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Ask an LLM. Picks the role's preferred model, retries on
        transient failures, falls through to the fallback chain on
        persistent failures.

        Returns an LLMResponse. On total failure, returns a response
        with success=False and an error message — never raises.
        """
        if not self._checked:
            self.auto_configure()

        # Build the full prompt with context
        full_prompt = prompt
        if context:
            try:
                ctx_str = json.dumps(context, default=str)[:2000]
                full_prompt = f"{prompt}\n\nContext: {ctx_str}"
            except Exception as exc:  # noqa: BLE001
                logger.debug("LLM context serialization failed: %s", exc)

        # Build the candidate model list: preferred → fallback chain
        preferred = self._role_map.get(role, self._role_map.get("general", ""))
        candidates: list[str] = []
        if preferred and preferred in self._configs:
            candidates.append(preferred)
        for name in self._fallback_chain:
            if name not in candidates and name in self._configs:
                candidates.append(name)
        # Last-resort: anything we have
        for name in self._configs:
            if name not in candidates:
                candidates.append(name)

        if not candidates:
            return LLMResponse(
                text="", model="", provider="none",
                success=False,
                error="No LLM providers configured. "
                      "Set SHOPAI_OLLAMA_URL or OPENAI_API_KEY or "
                      "ANTHROPIC_API_KEY.",
            )

        last_error = ""
        last_model = ""
        first_choice = candidates[0]

        for model_name in candidates:
            config = self._configs[model_name]
            call_started = time.monotonic()
            response, error = self._call_with_retry(
                config, full_prompt, system_prompt,
            )
            last_error = error
            last_model = model_name
            if response is not None:
                response.fallback_used = (model_name != first_choice)
                self._record_stats(model_name, response)
                return response

            # Persistent failure on this provider. Previously the loop
            # silently fell through to the next provider and the
            # failed model never showed up in stats — `calls=0,
            # errors=0` forever, so the dashboard couldn't tell a
            # 100%-failing provider from one that was never used.
            # Build a synthetic failure response and record it so
            # the operator can see the failure.
            failure = LLMResponse(
                text="",
                model=config.model,
                provider=config.provider,
                success=False,
                error=error,
                duration_s=round(time.monotonic() - call_started, 3),
                attempts=self._retry_attempts,
                fallback_used=(model_name != first_choice),
            )
            self._record_stats(model_name, failure)
            logger.warning(
                "LLM %s failed (%s); trying next in chain", model_name, error,
            )

        # Everything failed. Per-provider stats were already recorded
        # inside the loop above, so the dashboard reflects the full
        # picture. Just synthesize the final response for the caller.
        return LLMResponse(
            text="", model=last_model, provider="none",
            success=False, error=last_error or "All providers failed",
        )

    def ask_json(
        self,
        role: str,
        prompt: str,
        context: Optional[dict] = None,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        """Backwards-compatible: ask + best-effort JSON parse.

        Returns the parsed dict, or ``{"error": ..., "raw": ...}``
        on failure. Prefer ``ask_structured()`` for new code.
        """
        response = self.ask(role, prompt, context, system_prompt)
        if not response.success:
            return {"error": response.error}
        parsed = response.parse_json()
        if "raw" in parsed and len(parsed) == 1:
            return {"error": "could not parse JSON", "raw": parsed["raw"]}
        return parsed

    def ask_structured(
        self,
        role: str,
        prompt: str,
        *,
        schema_hint: Optional[str] = None,
        context: Optional[dict] = None,
        system_prompt: str = "",
    ) -> StructuredResponse:
        """Strict JSON-output version of ask().

        Adds a system instruction enforcing JSON-only output (so the
        model doesn't wrap the JSON in chatter), tries to parse the
        result, and returns a StructuredResponse with ok=True only
        when parsing actually succeeded.

        Args:
            role: which model to route to
            prompt: user-facing prompt
            schema_hint: optional brief description of the expected
                JSON shape (e.g. ``"{\\"items\\": [...], \\"total\\": int}"``).
                Included in the system prompt to nudge the model.
            context: extra dict appended to the prompt
            system_prompt: optional override of the JSON-mode system
                instruction

        Returns:
            StructuredResponse(ok, data, raw_text, error, response)
        """
        json_system = system_prompt or (
            "You output ONLY valid JSON. No prose, no markdown, no code "
            "fences. The first character of your response is '{' and the "
            "last is '}'. Use double quotes for keys and string values."
        )
        if schema_hint:
            json_system += f"\nExpected shape: {schema_hint}"

        response = self.ask(role, prompt, context, system_prompt=json_system)
        result = StructuredResponse(response=response, raw_text=response.text)

        if not response.success:
            result.error = response.error
            return result

        parsed = response.parse_json()
        if "raw" in parsed and len(parsed) == 1:
            result.error = "model did not return parseable JSON"
            return result

        result.ok = True
        result.data = parsed
        return result

    # ── Retry wrapper ─────────────────────────────────────────

    def _call_with_retry(
        self,
        config: LLMConfig,
        prompt: str,
        system_prompt: str,
    ) -> tuple[Optional[LLMResponse], str]:
        """Retry a single provider with exponential backoff.

        Returns (response, "") on success or (None, error_message)
        on persistent failure.
        """
        last_error = ""
        for attempt in range(1, self._retry_attempts + 1):
            start = time.monotonic()
            try:
                if config.provider == "ollama":
                    response = self._call_ollama(config, prompt, system_prompt)
                elif config.provider == "openai":
                    response = self._call_openai(config, prompt, system_prompt)
                elif config.provider == "anthropic":
                    response = self._call_anthropic(config, prompt, system_prompt)
                else:
                    return None, f"unknown provider: {config.provider}"

                response.duration_s = round(time.monotonic() - start, 3)
                response.attempts = attempt
                return response, ""

            except urllib.error.HTTPError as exc:
                # 4xx errors are not retriable
                last_error = f"HTTP {exc.code}: {exc.reason}"
                if 400 <= exc.code < 500 and exc.code != 429:
                    return None, last_error
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self._retry_attempts:
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.debug(
                    "LLM %s attempt %d/%d failed (%s), retrying in %.1fs",
                    config.model, attempt, self._retry_attempts,
                    last_error, delay,
                )
                time.sleep(delay)

        return None, last_error

    # ── Provider implementations ──────────────────────────────

    def _call_ollama(
        self, config: LLMConfig, prompt: str, system_prompt: str = "",
    ) -> LLMResponse:
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

    def _call_openai(
        self, config: LLMConfig, prompt: str, system_prompt: str = "",
    ) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }
        # Use OpenAI's JSON mode when the system prompt asked for JSON
        if config.supports_json_mode and system_prompt and (
            "json" in system_prompt.lower() or "{" in system_prompt
        ):
            body["response_format"] = {"type": "json_object"}

        payload = json.dumps(body).encode()
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

    def _call_anthropic(
        self, config: LLMConfig, prompt: str, system_prompt: str = "",
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            body["system"] = system_prompt

        data = json.dumps(body).encode()
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

        # Anthropic returns a list of content blocks
        text_blocks = [
            b.get("text", "") for b in result.get("content", [])
            if b.get("type") == "text"
        ]
        usage = result.get("usage", {})
        return LLMResponse(
            text="".join(text_blocks),
            model=config.model, provider="anthropic",
            tokens_used=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        )

    # ── Stats ─────────────────────────────────────────────────

    def _record_stats(self, model: str, response: LLMResponse) -> None:
        if model not in self._stats:
            self._stats[model] = {
                "calls": 0, "tokens": 0, "errors": 0,
                "total_time": 0.0, "fallback_uses": 0,
            }
        s = self._stats[model]
        s["calls"] += 1
        s["tokens"] += response.tokens_used
        s["total_time"] += response.duration_s
        if not response.success:
            s["errors"] += 1
        if response.fallback_used:
            s["fallback_uses"] += 1

    def get_stats(self) -> dict[str, Any]:
        return {
            "models": dict(self._stats),
            "configured": list(self._configs.keys()),
            "available_local": list(self._available_models),
            "role_map": dict(self._role_map),
            "fallback_chain": list(self._fallback_chain),
        }

    def get_available_models(self) -> list[str]:
        if not self._checked:
            self.auto_configure()
        return list(self._configs.keys())


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[LLMAdapter] = None
_instance_lock = _threading.Lock()


def get_llm() -> LLMAdapter:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LLMAdapter()
    return _instance
