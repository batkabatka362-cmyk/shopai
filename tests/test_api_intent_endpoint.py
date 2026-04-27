"""Tests for the ``POST /api/intent`` endpoint.

Exercises the handler through a real ``http.server`` instance —
same path as production, not a mock. Verifies routing, response
shape, and error paths.
"""
from __future__ import annotations

import json
import threading
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from api.server import ShopAIHandler


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), ShopAIHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    thread.join(timeout=2)


def _post(url: str, body: dict) -> tuple[int, dict]:
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


# ─── happy path ──────────────────────────────────────────────────


class TestIntentEndpointHappyPath:

    def test_classify_returns_engine_and_next_step(self, server: str):
        status, body = _post(
            f"{server}/api/intent",
            {"text": "create a 10% promo code"},
        )
        assert status == 200
        assert body["engine"] == "discount_strategy"
        assert body["confidence"] > 0.0
        assert body["source"] == "rules"
        assert "next_step" in body
        assert "POST /api/task" in body["next_step"]
        assert "discount_strategy" in body["next_step"]

    def test_classify_returns_alternatives(self, server: str):
        status, body = _post(
            f"{server}/api/intent",
            {"text": "increase prices to recover margins"},
        )
        assert status == 200
        assert isinstance(body["alternatives"], list)
        # At least one alternative typically surfaces for an
        # ambiguous business term like "margin".
        for alt in body["alternatives"]:
            assert "engine" in alt
            assert "confidence" in alt

    def test_classify_supports_query_alias(self, server: str):
        # ``query`` is an alternate to ``text``.
        status, body = _post(
            f"{server}/api/intent",
            {"query": "archive declining products"},
        )
        assert status == 200
        assert body["engine"] == "product_lifecycle"

    def test_classify_returns_matched_keywords(self, server: str):
        status, body = _post(
            f"{server}/api/intent",
            {"text": "auto-tag products by category"},
        )
        assert status == 200
        assert body["engine"] == "tag_management"
        assert isinstance(body["matched_keywords"], list)
        assert len(body["matched_keywords"]) > 0


# ─── no-match / weak match ──────────────────────────────────────


class TestIntentEndpointNoMatch:

    def test_gibberish_returns_supported_engines_menu(self, server: str):
        status, body = _post(
            f"{server}/api/intent",
            {"text": "xyzqq blarghhh"},
        )
        assert status == 200
        assert body["engine"] is None
        # Caller gets a menu when we couldn't route.
        assert "supported_engines" in body
        assert isinstance(body["supported_engines"], list)
        assert "discount_strategy" in body["supported_engines"]


# ─── input validation ──────────────────────────────────────────


class TestIntentEndpointInputValidation:

    def test_missing_text_returns_400(self, server: str):
        with pytest.raises(HTTPError) as ei:
            _post(f"{server}/api/intent", {})
        assert ei.value.code == 400
        body = json.loads(ei.value.read())
        assert "Missing 'text' field" in body["error"]
        assert "supported_engines" in body

    def test_empty_text_returns_400(self, server: str):
        with pytest.raises(HTTPError) as ei:
            _post(f"{server}/api/intent", {"text": ""})
        assert ei.value.code == 400

    def test_whitespace_text_returns_400(self, server: str):
        with pytest.raises(HTTPError) as ei:
            _post(f"{server}/api/intent", {"text": "   \n\t   "})
        assert ei.value.code == 400


# ─── multilingual routing ─────────────────────────────────────────


class TestIntentEndpointMultilingual:

    def test_mongolian_input_routes_correctly(self, server: str):
        status, body = _post(
            f"{server}/api/intent",
            {"text": "хямдрал хийе", "language": "mn"},
        )
        assert status == 200
        assert body["engine"] == "discount_strategy"
