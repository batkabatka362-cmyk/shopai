"""MCP handler tests for analyze_competitor + competitor_history.

Hits the registry end-to-end with a mocked ``http_get`` so we
exercise the full MCP path (registration, schema validation,
handler dispatch, return payload) without spending LLM budget
or hitting the network. Storage points at a pytest tmp dir so
production ``data/competitor_intel/`` never gets polluted.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from mcp_server.tools import ToolCall, build_default_registry


# ── Fake HTTP helper (duplicated here so MCP tests don't
#    pull the private symbol from the agent test module) ────


def _fake_http(stock: dict[str, dict]):
    def http_get(url: str):
        return stock.get(url, {"status": 404, "body": ""})
    return http_get


def _catalog_payload(product: str, price: str) -> str:
    return json.dumps({
        "products": [{
            "title": product,
            "handle": product.lower().replace(" ", "-"),
            "tags": "cozy",
            "product_type": "Light",
            "vendor": "V",
            "published_at": "2026-05-01T00:00:00Z",
            "variants": [{
                "price": price,
                "presentment_prices": [{
                    "price": {
                        "amount": price,
                        "currency_code": "USD",
                    },
                }],
            }],
        }],
    })


def _home_html(apps: list[str]) -> str:
    script_tags = "\n".join(
        f'<script src="https://{a}"></script>' for a in apps
    )
    return (
        '<html>'
        '<meta name="generator" content="Shopify Dawn 12.0">'
        f'{script_tags}<h1>Store</h1>'
        '</html>'
    )


def _stock(store: str, apps: list[str], product="Galaxy", price="29.99"):
    base = f"https://{store}"
    return {
        f"{base}/products.json?limit=250&page=1": {
            "status": 200,
            "body": _catalog_payload(product, price),
        },
        f"{base}/collections.json?limit=250": {
            "status": 200,
            "body": json.dumps({"collections": [{"handle": "a"}]}),
        },
        f"{base}/": {
            "status": 200,
            "body": _home_html(apps),
        },
    }


# ── analyze_competitor MCP handler ────────────────────────


class TestAnalyzeCompetitorMCP:
    def test_registered(self):
        reg = build_default_registry()
        names = {t.name for t in reg.list_tools()}
        assert "analyze_competitor" in names

    def test_rejects_empty_stores(self):
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="analyze_competitor",
            arguments={"stores": []},
        ))
        assert not res.ok
        assert "stores" in (res.error or "").lower()

    def test_stores_accepts_csv_string(self, tmp_path):
        """Some MCP clients serialise list args as CSV — handler
        must accept both shapes."""
        reg = build_default_registry()
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock("a.com", ["klaviyo"])),
        ):
            res = reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": "a.com",
                    "use_llm": False,
                    "persist": True,
                    "storage_dir": str(tmp_path),
                },
            ))
        assert res.ok, res.error
        assert res.content["count"] == 1
        assert res.content["reports"][0]["store"] == "a.com"

    def test_persist_produces_diff_on_second_call(self, tmp_path):
        reg = build_default_registry()
        # 1st scrape: one product at $29.99 with Klaviyo
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock(
                "b.com", ["static.klaviyo.com"],
                product="Galaxy", price="29.99",
            )),
        ):
            r1 = reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": ["b.com"],
                    "use_llm": False,
                    "storage_dir": str(tmp_path),
                },
            ))
        assert r1.ok
        assert r1.content["reports"][0]["diff"]["baseline"] is True

        # 2nd scrape: price +$5 + Meta Pixel added
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock(
                "b.com",
                ["static.klaviyo.com", "facebook.net/tr"],
                product="Galaxy", price="34.99",
            )),
        ):
            r2 = reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": ["b.com"],
                    "use_llm": False,
                    "storage_dir": str(tmp_path),
                },
            ))
        assert r2.ok
        d = r2.content["reports"][0]["diff"]
        assert d["baseline"] is False
        assert d["median_price_delta_usd"] == 5.0
        assert "Meta Pixel" in d["new_apps"]

    def test_persist_false_skips_history(self, tmp_path):
        reg = build_default_registry()
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock("c.com", [])),
        ):
            res = reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": ["c.com"],
                    "use_llm": False,
                    "persist": False,
                    "storage_dir": str(tmp_path),
                },
            ))
        assert res.ok
        assert res.content["persisted"] is False
        # No file created
        assert list(tmp_path.iterdir()) == []
        # No diff field on the report
        assert "diff" not in res.content["reports"][0]


# ── competitor_history MCP handler ────────────────────────


class TestCompetitorHistoryMCP:
    def test_registered(self):
        reg = build_default_registry()
        names = {t.name for t in reg.list_tools()}
        assert "competitor_history" in names

    def test_rejects_missing_store(self):
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="competitor_history",
            arguments={},
        ))
        assert not res.ok

    def test_empty_when_no_history(self, tmp_path):
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="competitor_history",
            arguments={
                "store": "unknown.com",
                "storage_dir": str(tmp_path),
            },
        ))
        assert res.ok
        assert res.content["count"] == 0
        assert res.content["history"] == []
        assert res.content["latest_diff"] == {}

    def test_baseline_after_one_scrape(self, tmp_path):
        reg = build_default_registry()
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock("d.com", [])),
        ):
            reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": ["d.com"],
                    "use_llm": False,
                    "storage_dir": str(tmp_path),
                },
            ))
        hist = reg.call(ToolCall(
            tool="competitor_history",
            arguments={
                "store": "d.com",
                "storage_dir": str(tmp_path),
            },
        ))
        assert hist.ok
        assert hist.content["count"] == 1
        assert hist.content["latest_diff"] == {"baseline": True}

    def test_diff_after_two_scrapes(self, tmp_path):
        reg = build_default_registry()
        # Scrape 1
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock(
                "e.com", ["static.klaviyo.com"], price="20.00",
            )),
        ):
            reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": ["e.com"],
                    "use_llm": False,
                    "storage_dir": str(tmp_path),
                },
            ))
        # Scrape 2 — different price + new app
        with patch(
            "agents.competitor_intel.agent._default_http_get",
            _fake_http(_stock(
                "e.com",
                ["static.klaviyo.com", "loox.io"],
                price="30.00",
            )),
        ):
            reg.call(ToolCall(
                tool="analyze_competitor",
                arguments={
                    "stores": ["e.com"],
                    "use_llm": False,
                    "storage_dir": str(tmp_path),
                },
            ))
        hist = reg.call(ToolCall(
            tool="competitor_history",
            arguments={
                "store": "e.com",
                "storage_dir": str(tmp_path),
            },
        ))
        assert hist.ok
        assert hist.content["count"] == 2
        d = hist.content["latest_diff"]
        assert d["baseline"] is False
        assert d["median_price_delta_usd"] == 10.0
        assert any("Loox" in a for a in d["new_apps"])
