"""End-to-end recording-style integration tests for the LLM stack.

Each test installs an in-memory fake at the urllib level that
records every request the system makes and returns
realistic-looking Ollama / OpenAI / Anthropic responses. The
fakes are calibrated to mimic the actual API shapes so the
adapter's parsing code is exercised on real-shaped data.

These exercise the FULL stack:

    cognitive module → prompt template → ask_structured()
        → LLMAdapter → urllib → fake transport
        → ollama-shaped response → parse_json → typed result
        → cognitive module consumes the result

If any of those layers regresses, one of these tests fails.

Why "recording-style": each fake response is a literal payload
that we'd see from the real provider. They're mostly snapshots
of small queries we'd actually run in production.
"""
import io
import json
import urllib.error
import urllib.request

import pytest


# ── Fake transport ───────────────────────────────────────────


class _RequestLog:
    """Captures every urllib.request.urlopen call for assertions."""

    def __init__(self):
        self.calls: list[dict] = []

    def add(self, req, body):
        self.calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(req.header_items()),
            "body": body,
        })


def _make_transport(responses, log):
    """Build a fake urlopen that returns canned responses keyed
    by URL substring."""

    class _FakeResp:
        def __init__(self, body_bytes, code=200):
            self._body = body_bytes
            self.code = code
            self.status = code

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return self._body

    def fake_urlopen(req, timeout=None):
        body_data = None
        if req.data:
            try:
                body_data = json.loads(req.data.decode("utf-8"))
            except Exception:
                body_data = req.data
        log.add(req, body_data)
        url = req.full_url
        for fragment, response in responses.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                if isinstance(response, dict):
                    payload = json.dumps(response).encode("utf-8")
                    return _FakeResp(payload)
                return _FakeResp(str(response).encode("utf-8"))
        # No match — return an empty response
        return _FakeResp(b"{}")

    return fake_urlopen


def _ollama_response(text, eval_count=42):
    """Build a payload that matches Ollama's /api/generate shape."""
    return {
        "model": "mistral",
        "created_at": "2026-04-07T12:00:00Z",
        "response": text,
        "done": True,
        "eval_count": eval_count,
        "eval_duration": 1500000000,
    }


def _ollama_tags(models):
    """Build a payload that matches Ollama's /api/tags shape."""
    return {
        "models": [
            {"name": f"{m}:latest", "modified_at": "2026-04-01T00:00:00Z",
             "size": 4_000_000_000}
            for m in models
        ],
    }


def _openai_response(text, total_tokens=42):
    """Build a payload that matches OpenAI's chat.completions shape."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1717000000,
        "model": "gpt-4o-mini",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": total_tokens},
    }


def _anthropic_response(text, in_tokens=10, out_tokens=20):
    """Build a payload that matches Anthropic's messages shape."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": in_tokens, "output_tokens": out_tokens},
    }


@pytest.fixture
def transport(monkeypatch):
    """Return a (log, install) pair. Tests call install(responses)
    once they've decided what the fake should return."""
    log = _RequestLog()

    def install(responses):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            _make_transport(responses, log),
        )
        return log

    return install


@pytest.fixture(autouse=True)
def fresh_llm():
    """Make sure the LLMAdapter singleton is rebuilt for every test
    so auto_configure runs with the test's fake transport."""
    from core.system import llm_adapter as la
    la._instance = None
    yield
    la._instance = None


# ── Adapter end-to-end ──────────────────────────────────────


class TestAdapterE2E:
    def test_ollama_simple_ask(self, transport, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://fake-ollama")
        log = transport({
            "fake-ollama/api/tags": _ollama_tags(["mistral"]),
            "fake-ollama/api/generate": _ollama_response(
                "Mistral says hi", eval_count=15,
            ),
        })

        from core.system.llm_adapter import get_llm
        llm = get_llm()
        resp = llm.ask("analyzer", "ping")

        assert resp.success
        assert "Mistral says hi" in resp.text
        assert resp.tokens_used == 15
        assert resp.provider == "ollama"
        assert resp.attempts == 1
        # Both /api/tags (auto_configure) and /api/generate were hit
        assert any("api/tags" in c["url"] for c in log.calls)
        assert any("api/generate" in c["url"] for c in log.calls)

    def test_openai_structured_json(self, transport, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://no-ollama-here")
        # Return tags-style failure for ollama (URL won't match);
        # OpenAI returns a clean JSON response with the action.
        log = transport({
            "openai.com": _openai_response(
                '{"action": "lower", "new_price": 27.99, "delta_pct": -6.7,'
                ' "reasoning": "below avg", "confidence": 0.7}',
                total_tokens=80,
            ),
        })

        from core.system.llm_adapter import get_llm
        llm = get_llm()
        result = llm.ask_structured(
            "analyzer", "What price?",
            schema_hint='{"action": str, "new_price": float}',
        )
        assert result.ok
        assert result.data["action"] == "lower"
        assert result.data["new_price"] == 27.99
        # Bearer token should have been on the request
        openai_calls = [c for c in log.calls if "openai.com" in c["url"]]
        assert openai_calls
        assert "Bearer sk-fake" in openai_calls[0]["headers"].get("Authorization", "")
        # response_format JSON mode should have been requested
        assert openai_calls[0]["body"].get("response_format") == {"type": "json_object"}

    def test_fallback_chain_works(self, transport, monkeypatch):
        # Ollama listed but generate fails; OpenAI responds.
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://fake-ollama")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        # auto_configure first hits /api/tags. We make that succeed
        # so ollama is registered, then make /api/generate fail.
        log = transport({
            "fake-ollama/api/tags": _ollama_tags(["mistral"]),
            "fake-ollama/api/generate": urllib.error.URLError("connection refused"),
            "openai.com": _openai_response("from openai", total_tokens=20),
        })

        from core.system.llm_adapter import get_llm
        llm = get_llm()
        llm.set_retry_policy(1, base_delay=0.0)  # don't waste test time
        resp = llm.ask("analyzer", "hello")
        assert resp.success
        assert "from openai" in resp.text
        assert resp.fallback_used is True


# ── Cognitive module end-to-end ─────────────────────────────


class TestReflectionE2E:
    def test_real_reflection_against_fake_ollama(self, transport, monkeypatch):
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://fake-ollama")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # The Ollama response is the literal JSON the model would
        # return for the reflection.summarize_episodes prompt
        llm_payload = {
            "lessons": [
                {
                    "type": "weekend_pattern",
                    "subject": "pricing",
                    "evidence": "All 4 failures happened on weekends",
                    "recommended_action": "skip pricing on Sat/Sun",
                    "confidence": 0.85,
                },
            ],
        }
        transport({
            "fake-ollama/api/tags": _ollama_tags(["mistral"]),
            "fake-ollama/api/generate": _ollama_response(
                json.dumps(llm_payload),
            ),
        })

        # Build a real Reflection with a real fake-memory
        from core.cognitive.reflection import Reflection
        from tests.test_reflection import FakeMemory
        mem = FakeMemory()
        for i in range(8):
            mem.add("action", action="pricing", score=4.0 if i < 4 else 1.5)

        r = Reflection(memory=mem)  # llm auto-resolved
        report = r.reflect(apply=False)
        # Should have at least one llm:* lesson
        llm_lessons = [l for l in report.lessons if l.type.startswith("llm:")]
        assert len(llm_lessons) == 1
        assert llm_lessons[0].subject == "pricing"
        assert "weekend" in llm_lessons[0].evidence.lower()
        assert llm_lessons[0].confidence == 0.85


class TestPricingIntelligenceE2E:
    def test_real_pricing_recommendation_via_fake_ollama(self, transport, monkeypatch):
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://fake-ollama")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        llm_payload = {
            "action": "lower",
            "new_price": 26.99,
            "delta_pct": -10.0,
            "reasoning": "Below competitor average to win share",
            "confidence": 0.75,
            "risks": ["margin compression"],
        }
        transport({
            "fake-ollama/api/tags": _ollama_tags(["mistral"]),
            "fake-ollama/api/generate": _ollama_response(
                json.dumps(llm_payload),
            ),
        })

        from core.intelligence.pricing_intelligence import PricingIntelligence
        pi = PricingIntelligence()  # llm auto-resolved
        result = pi.recommend_with_llm(
            {"name": "Cozy Lamp", "price": 29.99, "cost": 12.50},
            competitor_prices=[28.50, 30.00, 27.99],
        )
        assert result["source"] == "llm"
        rec = result["llm"]
        assert rec["action"] == "lower"
        assert rec["new_price"] == 26.99
        assert rec["confidence"] == 0.75
        assert "margin compression" in rec["risks"]
        # Heuristic also present (always)
        assert result["heuristic"]["competitor_count"] == 3


class TestContentGeneratorE2E:
    def test_real_product_description_via_fake_ollama(self, transport, monkeypatch):
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://fake-ollama")
        llm_payload = {
            "headline": "Wrap Yourself in Wool Luxury",
            "subheadline": "Pure merino, hand finished",
            "body": "Real merino wool. Machine washable. Queen size.",
            "bullets": ["100% merino", "Machine washable", "Queen size"],
            "meta_description": "Premium merino wool blanket queen size",
        }
        transport({
            "fake-ollama/api/tags": _ollama_tags(["mistral", "llama3.2"]),
            "fake-ollama/api/generate": _ollama_response(
                json.dumps(llm_payload),
            ),
        })

        from core.intelligence.content_generator import ContentGenerator
        cg = ContentGenerator()
        result = cg.product_description_with_llm(
            {
                "name": "Cozy Wool Blanket",
                "category": "home",
                "features": ["100% merino", "queen size"],
            },
            tone="warm",
        )
        assert result["source"] == "llm"
        assert "Wool Luxury" in result["llm"]["headline"]
        assert len(result["llm"]["bullets"]) == 3


# ── Stats sanity ────────────────────────────────────────────


class TestStatsRoundtrip:
    def test_stats_track_real_calls(self, transport, monkeypatch):
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "http://fake-ollama")
        transport({
            "fake-ollama/api/tags": _ollama_tags(["mistral"]),
            "fake-ollama/api/generate": _ollama_response("hi", eval_count=10),
        })
        from core.system.llm_adapter import get_llm
        llm = get_llm()
        llm.ask("analyzer", "ping1")
        llm.ask("analyzer", "ping2")
        stats = llm.get_stats()
        assert stats["models"]["mistral"]["calls"] == 2
        assert stats["models"]["mistral"]["tokens"] == 20
