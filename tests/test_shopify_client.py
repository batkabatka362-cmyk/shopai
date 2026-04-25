"""Tests for the shared Shopify REST client."""
import io
import json
import threading
import time
from unittest.mock import patch

import pytest


def _make_client(**kwargs):
    from utils.shopify_client import ShopifyClient
    defaults = {"rate_limit": 1000.0}  # high rate so tests aren't throttled
    defaults.update(kwargs)
    return ShopifyClient("test.myshopify.com", "shpat_x", **defaults)


class _FakeResp:
    def __init__(self, body: bytes, code: int = 200):
        self._body = body
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return self._body


class _FakeHTTPError(Exception):
    def __init__(self, code: int, body: bytes = b""):
        self.code = code
        self._body = body
        super().__init__(f"HTTP {code}")

    def read(self):
        return self._body


class TestUrlBuilding:
    def test_path_no_params(self):
        c = _make_client()
        assert c._build_url("products.json", None) == (
            "https://test.myshopify.com/admin/api/2024-01/products.json"
        )

    def test_leading_slash_stripped(self):
        c = _make_client()
        assert c._build_url("/pages.json", None).endswith("/pages.json")

    def test_params_added(self):
        c = _make_client()
        url = c._build_url("products.json", {"limit": 50})
        assert url.endswith("products.json?limit=50")

    def test_custom_api_version(self):
        c = _make_client(api_version="2025-01")
        assert "/api/2025-01/" in c._build_url("x.json", None)


class TestGet:
    def test_success_returns_parsed_json(self, monkeypatch):
        c = _make_client()
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout: _FakeResp(b'{"products": [{"id": 1}]}'),
        )
        result = c.get("products.json")
        assert result == {"products": [{"id": 1}]}

    def test_http_error_returns_error_dict(self, monkeypatch):
        c = _make_client()
        import urllib.error
        err = urllib.error.HTTPError(
            "http://x", 404, "Not Found", {}, io.BytesIO(b'{"error":"not found"}'),
        )

        def raise_err(*a, **kw):
            raise err

        monkeypatch.setattr("urllib.request.urlopen", raise_err)
        result = c.get("missing.json")
        assert "error" in result
        assert result["status_code"] == 404

    def test_invalid_json_returns_error(self, monkeypatch):
        c = _make_client()
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout: _FakeResp(b"<html>not json</html>"),
        )
        result = c.get("x.json")
        assert "error" in result


class TestPostPut:
    def test_post_sends_body(self, monkeypatch):
        c = _make_client()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["headers"] = dict(req.header_items())
            return _FakeResp(b'{"page": {"id": 99}}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = c.post("pages.json", json={"page": {"title": "T"}})
        assert result == {"page": {"id": 99}}
        assert captured["method"] == "POST"
        assert json.loads(captured["data"]) == {"page": {"title": "T"}}
        assert captured["headers"]["X-shopify-access-token"] == "shpat_x"

    def test_put_uses_put_method(self, monkeypatch):
        c = _make_client()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["method"] = req.get_method()
            return _FakeResp(b'{}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        c.put("products/1.json", json={"product": {"id": 1}})
        assert captured["method"] == "PUT"


class TestGraphQL:
    def test_graphql_posts_to_graphql_endpoint(self, monkeypatch):
        c = _make_client()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["data"] = json.loads(req.data.decode())
            return _FakeResp(b'{"data": {"shop": {"name": "T"}}}')

        monkeypatch.setattr(
            "urllib.request.urlopen", fake_urlopen,
        )
        out = c.graphql(
            "query { shop { name } }",
        )
        assert out == {"data": {"shop": {"name": "T"}}}
        assert "graphql.json" in captured["url"]
        assert captured["method"] == "POST"
        assert captured["data"]["query"] == "query { shop { name } }"

    def test_graphql_passes_variables(self, monkeypatch):
        c = _make_client()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["data"] = json.loads(req.data.decode())
            return _FakeResp(b'{"data": null}')

        monkeypatch.setattr(
            "urllib.request.urlopen", fake_urlopen,
        )
        c.graphql(
            "mutation($x: String!) { ping(x: $x) }",
            variables={"x": "hello"},
        )
        assert captured["data"]["variables"] == {"x": "hello"}

    def test_graphql_errors_surface_under_error_key(
        self, monkeypatch,
    ):
        """Shopify GraphQL errors come as ``errors[]`` in a
        200 body — we promote them to the ``error`` key so
        callers can do a uniform ``if "error" in resp:`` check."""
        c = _make_client()

        def fake_urlopen(req, timeout):
            return _FakeResp(
                b'{"errors": [{"message": "bad field"}], '
                b'"data": null}',
            )

        monkeypatch.setattr(
            "urllib.request.urlopen", fake_urlopen,
        )
        out = c.graphql("query { noSuchField }")
        assert "error" in out
        assert "bad field" in out["error"]
        assert out["errors"] == [{"message": "bad field"}]

    def test_graphql_http_error_returns_error_dict(
        self, monkeypatch,
    ):
        c = _make_client()

        def fake_urlopen(req, timeout):
            import urllib.error
            raise urllib.error.HTTPError(
                req.full_url, 500, "Server Error",
                {}, io.BytesIO(b'{"error": "oops"}'),
            )

        monkeypatch.setattr(
            "urllib.request.urlopen", fake_urlopen,
        )
        out = c.graphql("query { shop { name } }")
        assert "error" in out


class TestRetry:
    def test_retries_on_429(self, monkeypatch):
        c = _make_client()
        import urllib.error
        attempts = {"n": 0}

        def fake(req, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise urllib.error.HTTPError(
                    "http://x", 429, "Too Many Requests", {},
                    io.BytesIO(b"rate limited"),
                )
            return _FakeResp(b'{"ok": true}')

        monkeypatch.setattr("urllib.request.urlopen", fake)
        monkeypatch.setattr("time.sleep", lambda _: None)  # skip backoff
        result = c.get("x.json")
        assert result == {"ok": True}
        assert attempts["n"] == 3

    def test_retries_exhausted_returns_error(self, monkeypatch):
        c = _make_client()
        import urllib.error

        def fake(req, timeout):
            raise urllib.error.HTTPError(
                "http://x", 503, "Unavailable", {}, io.BytesIO(b""),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake)
        monkeypatch.setattr("time.sleep", lambda _: None)
        result = c.get("x.json")
        assert result.get("status_code") == 503

    def test_no_retry_on_4xx_except_429(self, monkeypatch):
        c = _make_client()
        import urllib.error
        attempts = {"n": 0}

        def fake(req, timeout):
            attempts["n"] += 1
            raise urllib.error.HTTPError(
                "http://x", 422, "Unprocessable", {},
                io.BytesIO(b'{"errors": "bad"}'),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake)
        c.post("x.json", json={})
        assert attempts["n"] == 1  # no retries


class TestRateLimit:
    def test_bucket_enforces_rate(self):
        from utils.shopify_client import _TokenBucket
        # 5 req/sec, burst 2
        bucket = _TokenBucket(rate_per_sec=5.0, burst=2)
        # Consume burst instantly
        t0 = time.monotonic()
        bucket.take()
        bucket.take()
        # Next take should wait at least 1/5s = 0.2s
        bucket.take()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.15  # allow some slack

    def test_bucket_thread_safe(self):
        from utils.shopify_client import _TokenBucket
        bucket = _TokenBucket(rate_per_sec=1000.0, burst=10)
        counter = {"n": 0}
        lock = threading.Lock()

        def worker():
            for _ in range(20):
                bucket.take()
                with lock:
                    counter["n"] += 1

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert counter["n"] == 100
