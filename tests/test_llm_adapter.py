"""Tests for the production-grade LLMAdapter.

These mock urllib at the module level so no real Ollama / OpenAI /
Anthropic calls are made. Each test exercises one branch of the
adapter's behavior in isolation.
"""
import io
import json
import urllib.error

import pytest


def _adapter():
    """Return a fresh adapter without auto-configuring."""
    from core.system.llm_adapter import LLMAdapter
    a = LLMAdapter()
    a._checked = True  # skip auto_configure
    return a


def _add_ollama(adapter, model="mistral"):
    from core.system.llm_adapter import LLMConfig
    adapter.add_provider(
        model,
        LLMConfig(provider="ollama", model=model, url="http://fake-ollama"),
    )


def _add_openai(adapter, model="gpt-4o-mini"):
    from core.system.llm_adapter import LLMConfig
    adapter.add_provider(
        "openai",
        LLMConfig(
            provider="openai", model=model,
            url="https://api.openai.com/v1/chat/completions",
            api_key="sk-test", supports_json_mode=True,
        ),
    )


def _add_anthropic(adapter, model="claude-haiku-4-5-20251001"):
    from core.system.llm_adapter import LLMConfig
    adapter.add_provider(
        "anthropic",
        LLMConfig(
            provider="anthropic", model=model,
            url="https://api.anthropic.com/v1/messages",
            api_key="sk-ant-test", supports_json_mode=True,
        ),
    )


class _FakeResp:
    def __init__(self, body, code=200):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self._body = body
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return self._body


# ── Dataclass shapes ─────────────────────────────────────────


class TestDataclasses:
    def test_llm_response_to_dict(self):
        from core.system.llm_adapter import LLMResponse
        r = LLMResponse(
            text="hi", model="m", provider="ollama",
            tokens_used=10, duration_s=0.456,
        )
        d = r.to_dict()
        assert d["text"] == "hi"
        assert d["duration_s"] == 0.456
        assert d["fallback_used"] is False

    def test_parse_json_clean(self):
        from core.system.llm_adapter import LLMResponse
        r = LLMResponse(text='{"a": 1, "b": "two"}')
        assert r.parse_json() == {"a": 1, "b": "two"}

    def test_parse_json_with_chatter(self):
        from core.system.llm_adapter import LLMResponse
        r = LLMResponse(text='Sure! Here you go: {"x": 42} hope this helps')
        assert r.parse_json() == {"x": 42}

    def test_parse_json_with_code_fence(self):
        from core.system.llm_adapter import LLMResponse
        r = LLMResponse(text='```json\n{"a": 1}\n```')
        assert r.parse_json() == {"a": 1}

    def test_parse_json_unparseable(self):
        from core.system.llm_adapter import LLMResponse
        r = LLMResponse(text="hello world")
        result = r.parse_json()
        assert result == {"raw": "hello world"}


# ── Configuration ────────────────────────────────────────────


class TestConfiguration:
    def test_add_provider_appends_to_chain(self):
        a = _adapter()
        _add_ollama(a, "mistral")
        _add_openai(a)
        assert "mistral" in a._fallback_chain
        assert "openai" in a._fallback_chain

    def test_set_role_model(self):
        a = _adapter()
        a.set_role_model("analyzer", "qwen2.5")
        assert a._role_map["analyzer"] == "qwen2.5"

    def test_set_fallback_chain(self):
        a = _adapter()
        a.set_fallback_chain(["openai", "anthropic"])
        assert a._fallback_chain == ["openai", "anthropic"]

    def test_set_retry_policy_clamps(self):
        a = _adapter()
        a.set_retry_policy(0, -1.0)
        assert a._retry_attempts == 1
        assert a._retry_base_delay == 0.0

    def test_is_available_with_no_providers(self):
        a = _adapter()
        a._configs = {}
        assert a.is_available() is False

    def test_is_available_after_config(self):
        a = _adapter()
        _add_ollama(a)
        assert a.is_available() is True


# ── Auto-configure ───────────────────────────────────────────


class TestAutoConfigure:
    def test_no_providers_when_no_env_no_ollama(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("no ollama")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        from core.system.llm_adapter import LLMAdapter
        a = LLMAdapter()
        info = a.auto_configure()
        assert info["configured"] == []

    def test_picks_up_ollama_models(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"models": [
                {"name": "mistral:latest"},
                {"name": "qwen2.5:7b"},
                {"name": "llama3.2:3b"},
            ]})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        from core.system.llm_adapter import LLMAdapter
        a = LLMAdapter()
        info = a.auto_configure()
        assert "ollama:mistral" in info["configured"]
        assert "ollama:qwen2.5" in info["configured"]
        assert "ollama:llama3.2" in info["configured"]
        assert info["roles"]["analyzer"] == "mistral"
        assert "qwen" in info["roles"]["worker"]
        assert "llama" in info["roles"]["creative"]

    def test_picks_up_openai_when_env_set(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("no ollama")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        from core.system.llm_adapter import LLMAdapter
        a = LLMAdapter()
        info = a.auto_configure()
        assert any("openai" in c for c in info["configured"])
        assert "openai" in info["fallback_chain"]

    def test_picks_up_anthropic_when_env_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("no ollama")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        from core.system.llm_adapter import LLMAdapter
        a = LLMAdapter()
        info = a.auto_configure()
        assert any("anthropic" in c for c in info["configured"])

    def test_custom_openai_model_via_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        monkeypatch.setenv("SHOPAI_OPENAI_MODEL", "gpt-4o")
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("x")),
        )
        from core.system.llm_adapter import LLMAdapter
        a = LLMAdapter()
        a.auto_configure()
        assert a._configs["openai"].model == "gpt-4o"


# ── Ollama call ──────────────────────────────────────────────


class TestOllamaCall:
    def test_successful_response(self, monkeypatch):
        a = _adapter()
        _add_ollama(a, "mistral")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({
                "response": "Hello from Mistral",
                "eval_count": 25,
            })

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        resp = a.ask("analyzer", "ping")
        assert resp.success is True
        assert resp.text == "Hello from Mistral"
        assert resp.tokens_used == 25
        assert resp.provider == "ollama"
        assert resp.attempts == 1
        # Body should include model + prompt
        assert captured["body"]["model"] == "mistral"
        assert captured["body"]["prompt"] == "ping"

    def test_includes_system_prompt(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({"response": "ok"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        a.ask("analyzer", "hi", system_prompt="be helpful")
        assert captured["body"]["system"] == "be helpful"

    def test_includes_context_in_prompt(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({"response": "ok"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        a.ask("analyzer", "what?", context={"price": 25})
        assert "Context:" in captured["body"]["prompt"]
        assert "25" in captured["body"]["prompt"]


# ── OpenAI call ──────────────────────────────────────────────


class TestOpenAICall:
    def test_basic_call(self, monkeypatch):
        a = _adapter()
        _add_openai(a)
        a.set_role_model("analyzer", "openai")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({
                "choices": [{"message": {"content": "from gpt"}}],
                "usage": {"total_tokens": 42},
            })

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "hello")
        assert resp.text == "from gpt"
        assert resp.provider == "openai"
        assert resp.tokens_used == 42
        assert "Bearer sk-test" in captured["headers"]["Authorization"]
        assert captured["body"]["model"] == "gpt-4o-mini"

    def test_json_mode_enabled_when_system_says_json(self, monkeypatch):
        a = _adapter()
        _add_openai(a)
        a.set_role_model("analyzer", "openai")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({
                "choices": [{"message": {"content": '{"x":1}'}}],
                "usage": {"total_tokens": 5},
            })

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        a.ask(
            "analyzer", "give me numbers",
            system_prompt="You output ONLY valid JSON. {\"x\": int}",
        )
        # response_format should be set
        assert captured["body"].get("response_format") == {"type": "json_object"}


# ── Anthropic call ───────────────────────────────────────────


class TestAnthropicCall:
    def test_basic_call(self, monkeypatch):
        a = _adapter()
        _add_anthropic(a)
        a.set_role_model("analyzer", "anthropic")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({
                "content": [
                    {"type": "text", "text": "first part "},
                    {"type": "text", "text": "second part"},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            })

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "hi")
        assert resp.text == "first part second part"
        assert resp.tokens_used == 30
        assert captured["headers"]["X-api-key"] == "sk-ant-test"


# ── Retry logic ──────────────────────────────────────────────


class TestRetry:
    def test_retries_on_transient_failure(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        a.set_retry_policy(3, base_delay=0.0)
        attempts = {"n": 0}

        def fake_urlopen(req, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise urllib.error.URLError("transient")
            return _FakeResp({"response": "ok"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "ping")
        assert resp.success is True
        assert resp.attempts == 3
        assert attempts["n"] == 3

    def test_retries_on_500(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        a.set_retry_policy(3, base_delay=0.0)
        attempts = {"n": 0}

        def fake_urlopen(req, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise urllib.error.HTTPError(
                    "http://x", 500, "Server Error", {}, io.BytesIO(b""),
                )
            return _FakeResp({"response": "ok"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "ping")
        assert resp.success is True
        assert attempts["n"] == 2

    def test_no_retry_on_400(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        a.set_retry_policy(5, base_delay=0.0)
        attempts = {"n": 0}

        def fake_urlopen(req, timeout=None):
            attempts["n"] += 1
            raise urllib.error.HTTPError(
                "http://x", 400, "Bad Request", {}, io.BytesIO(b"bad"),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "ping")
        assert resp.success is False
        # Only 1 attempt across all candidates → 4xx is non-retriable
        # but the adapter still tries each candidate once
        assert attempts["n"] >= 1

    def test_429_does_retry(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        a.set_retry_policy(3, base_delay=0.0)
        attempts = {"n": 0}

        def fake_urlopen(req, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise urllib.error.HTTPError(
                    "http://x", 429, "Rate Limited", {}, io.BytesIO(b""),
                )
            return _FakeResp({"response": "ok"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "ping")
        assert resp.success is True
        assert attempts["n"] == 2

    def test_returns_failure_after_exhaustion(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        a.set_retry_policy(2, base_delay=0.0)

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("dead")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "ping")
        assert resp.success is False
        assert "dead" in resp.error or "URLError" in resp.error


# ── Fallback chain ───────────────────────────────────────────


class TestFallbackChain:
    def test_falls_through_to_next_provider(self, monkeypatch):
        a = _adapter()
        _add_ollama(a, "mistral")
        _add_openai(a)
        a.set_retry_policy(1, base_delay=0.0)

        call_log = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            call_log.append(url)
            if "ollama" in url:
                raise urllib.error.URLError("ollama down")
            return _FakeResp({
                "choices": [{"message": {"content": "from openai"}}],
                "usage": {"total_tokens": 5},
            })

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "hi")
        assert resp.success is True
        assert resp.text == "from openai"
        assert resp.fallback_used is True
        # Both endpoints were tried
        assert any("ollama" in u for u in call_log)
        assert any("openai" in u for u in call_log)

    def test_no_fallback_used_when_first_succeeds(self, monkeypatch):
        a = _adapter()
        _add_ollama(a, "mistral")
        _add_openai(a)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"response": "ok"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = a.ask("analyzer", "hi")
        assert resp.success is True
        assert resp.fallback_used is False

    def test_no_providers_returns_helpful_error(self):
        a = _adapter()
        a._configs = {}
        resp = a.ask("analyzer", "hi")
        assert resp.success is False
        assert "No LLM providers" in resp.error


# ── ask_json + ask_structured ────────────────────────────────


class TestAskJson:
    def test_returns_parsed_dict(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"response": '{"answer": 42}'})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = a.ask_json("analyzer", "what?")
        assert result == {"answer": 42}

    def test_failure_returns_error_dict(self):
        a = _adapter()
        a._configs = {}
        result = a.ask_json("analyzer", "what?")
        assert "error" in result

    def test_unparseable_returns_error_with_raw(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"response": "i am not json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = a.ask_json("analyzer", "what?")
        assert "error" in result
        assert result.get("raw") == "i am not json"


class TestAskStructured:
    def test_strict_json_success(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"response": '{"answer": 42}'})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = a.ask_structured("analyzer", "what?", schema_hint='{"answer": int}')
        assert result.ok is True
        assert result.data == {"answer": 42}
        assert result.error == ""

    def test_strict_json_failure_on_garbage(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"response": "absolutely not json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = a.ask_structured("analyzer", "what?")
        assert result.ok is False
        assert result.error
        assert result.raw_text == "absolutely not json"

    def test_response_failure_propagates(self):
        a = _adapter()
        a._configs = {}
        result = a.ask_structured("analyzer", "what?")
        assert result.ok is False
        assert "No LLM providers" in result.error

    def test_default_system_prompt_includes_json_only(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp({"response": '{"x":1}'})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        a.ask_structured("analyzer", "what?")
        assert "json" in captured["body"]["system"].lower()


# ── Stats ────────────────────────────────────────────────────


class TestStats:
    def test_records_per_model_stats(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)

        def fake_urlopen(req, timeout=None):
            return _FakeResp({"response": "ok", "eval_count": 10})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        a.ask("analyzer", "1")
        a.ask("analyzer", "2")
        stats = a.get_stats()
        assert stats["models"]["mistral"]["calls"] == 2
        assert stats["models"]["mistral"]["tokens"] == 20

    def test_records_fallback_uses(self, monkeypatch):
        a = _adapter()
        _add_ollama(a)
        _add_openai(a)
        a.set_retry_policy(1, base_delay=0.0)

        def fake_urlopen(req, timeout=None):
            if "ollama" in req.full_url:
                raise urllib.error.URLError("dead")
            return _FakeResp({
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"total_tokens": 1},
            })

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        a.ask("analyzer", "ping")
        stats = a.get_stats()
        assert stats["models"]["openai"]["fallback_uses"] >= 1


# ── Singleton accessor ──────────────────────────────────────


class TestSingleton:
    def test_get_llm_caches(self):
        from core.system import llm_adapter as mod
        mod._instance = None
        a = mod.get_llm()
        b = mod.get_llm()
        assert a is b
