"""LLM Connector — connects to any LLM provider for real AI text generation.

Supports: Ollama (local), OpenAI API, Anthropic API, any OpenAI-compatible API.
Falls back to heuristic when no LLM available.
"""
from __future__ import annotations
import json
import os
import urllib.request
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("llm.connector")


class LLMConnector:
    """Universal LLM connector — try providers in order until one works."""

    def __init__(self) -> None:
        self._providers: list[dict] = []
        self._active: str = ""
        self._call_count = 0
        self._auto_configure()

    def _auto_configure(self) -> None:
        # 1. Ollama (local)
        ollama_url = os.environ.get("SHOPAI_OLLAMA_URL", "http://localhost:11434")
        self._providers.append({
            "name": "ollama",
            "url": ollama_url,
            "type": "ollama",
        })

        # 2. OpenAI-compatible (if configured)
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            self._providers.append({
                "name": "openai",
                "url": "https://api.openai.com/v1",
                "key": openai_key,
                "type": "openai",
                "model": os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
            })

        # 3. Anthropic (if configured)
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            self._providers.append({
                "name": "anthropic",
                "url": "https://api.anthropic.com/v1",
                "key": anthropic_key,
                "type": "anthropic",
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            })

    def ask(self, prompt: str, role: str = "assistant",
            max_tokens: int = 500) -> str:
        """Ask LLM a question. Tries providers in order."""
        for provider in self._providers:
            try:
                if provider["type"] == "ollama":
                    result = self._ask_ollama(provider, prompt, max_tokens)
                elif provider["type"] == "openai":
                    result = self._ask_openai(provider, prompt, role, max_tokens)
                elif provider["type"] == "anthropic":
                    result = self._ask_anthropic(provider, prompt, max_tokens)
                else:
                    continue

                if result:
                    self._active = provider["name"]
                    self._call_count += 1
                    return result
            except Exception:
                continue

        # All failed — return empty (caller should use heuristic)
        return ""

    def _ask_ollama(self, provider: dict, prompt: str, max_tokens: int) -> str:
        url = "{}/api/generate".format(provider["url"])
        payload = json.dumps({
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }).encode()
        req = urllib.request.Request(url, data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("response", "")

    def _ask_openai(self, provider: dict, prompt: str,
                    role: str, max_tokens: int) -> str:
        url = "{}/chat/completions".format(provider["url"])
        payload = json.dumps({
            "model": provider.get("model", "gpt-3.5-turbo"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(url, data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(provider["key"]),
            })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]

    def _ask_anthropic(self, provider: dict, prompt: str, max_tokens: int) -> str:
        url = "{}/messages".format(provider["url"])
        payload = json.dumps({
            "model": provider.get("model", "claude-haiku-4-5-20251001"),
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(url, data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": provider["key"],
                "anthropic-version": "2023-06-01",
            })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"]

    def is_available(self) -> bool:
        """Check if any LLM provider is reachable."""
        for p in self._providers:
            try:
                if p["type"] == "ollama":
                    req = urllib.request.Request("{}/api/tags".format(p["url"]))
                    urllib.request.urlopen(req, timeout=3)
                    return True
                elif p.get("key"):
                    return True  # Has API key configured
            except Exception:
                continue
        return False

    def get_stats(self) -> dict:
        return {
            "providers": len(self._providers),
            "active": self._active,
            "calls": self._call_count,
            "available": self.is_available(),
            "provider_list": [p["name"] for p in self._providers],
        }


_instance = None
def get_llm_connector():
    global _instance
    if _instance is None:
        _instance = LLMConnector()
    return _instance
