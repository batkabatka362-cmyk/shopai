"""StoreConfigurator policies feature tests (Phase 1f).

Uses the new GraphQL helper to update all four legal policies
(privacy / refund / ToS / shipping). Required for GDPR + Meta
ads policy auditor on any paid-acquisition storefront.
"""
from __future__ import annotations

import pytest


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(
    monkeypatch, responses=None, track_calls=None,
):
    responses = responses or {}
    track_calls = (
        track_calls if track_calls is not None else []
    )

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            self.shop_url = shop_url

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return responses.get(f"GET {path}", {})

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return responses.get(f"POST {path}", {})

        def put(self, path, *, json=None):
            track_calls.append(("PUT", path, json))
            return responses.get(f"PUT {path}", {})

        def delete(self, path):
            track_calls.append(("DELETE", path, None))
            return responses.get(f"DELETE {path}", {})

        def graphql(self, query, variables=None):
            track_calls.append((
                "GRAPHQL", "graphql.json", variables,
            ))
            return responses.get(
                "GRAPHQL", {
                    "data": {
                        "shopPolicyUpdate": {
                            "userErrors": [],
                            "shopPolicy": {
                                "id": "gid://1",
                                "type": (
                                    variables["policy"]["type"]
                                    if variables else ""
                                ),
                                "body": "<h1>ok</h1>",
                            },
                        },
                    },
                },
            )

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )
    return track_calls


class TestPoliciesFeatureEnabled:
    def test_policies_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "policies" in ALL_FEATURES


class TestPoliciesDryRun:
    def test_all_four_policies_planned(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="beauty", store_name="Glow Co",
            features=["policies"],
        )
        pol = result["results"]["policies"]
        assert pol["status"] == "dry_run"
        assert set(pol["updated"]) == {
            "PRIVACY_POLICY", "REFUND_POLICY",
            "TERMS_OF_SERVICE", "SHIPPING_POLICY",
        }
        assert pol["errors"] == []

    def test_dry_run_records_plan_entries(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="general",
            features=["policies"],
        )
        plan = result["plan"]
        policy_entries = [
            e for e in plan
            if e.get("action") == "update_policy"
        ]
        assert len(policy_entries) == 4


class TestPoliciesLive:
    def test_calls_graphql_for_each_policy(
        self, monkeypatch,
    ):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="tech", store_name="Gadget Hub",
            features=["policies"],
        )
        graphql_calls = [
            call for call in calls
            if call[0] == "GRAPHQL"
        ]
        assert len(graphql_calls) == 4
        types_posted = {
            call[2]["policy"]["type"]
            for call in graphql_calls
        }
        assert types_posted == {
            "PRIVACY_POLICY", "REFUND_POLICY",
            "TERMS_OF_SERVICE", "SHIPPING_POLICY",
        }
        pol = result["results"]["policies"]
        assert pol["status"] == "success"
        assert len(pol["updated"]) == 4

    def test_user_errors_recorded_as_errors(
        self, monkeypatch,
    ):
        _install_fake_client(
            monkeypatch,
            responses={
                "GRAPHQL": {
                    "data": {
                        "shopPolicyUpdate": {
                            "userErrors": [
                                {
                                    "field": "body",
                                    "message": "too short",
                                },
                            ],
                            "shopPolicy": None,
                        },
                    },
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["policies"],
        )
        pol = result["results"]["policies"]
        assert pol["status"] == "partial"
        assert len(pol["errors"]) == 4
        for e in pol["errors"]:
            assert "too short" in e["error"]

    def test_graphql_transport_error_isolated(
        self, monkeypatch,
    ):
        _install_fake_client(
            monkeypatch,
            responses={
                "GRAPHQL": {"error": "rate limited"},
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["policies"],
        )
        pol = result["results"]["policies"]
        assert pol["status"] == "partial"
        assert pol["updated"] == []
        assert len(pol["errors"]) == 4


class TestPolicyTemplates:
    def test_four_policies(self):
        from execution.store_configurator import (
            _policy_templates,
        )
        pols = _policy_templates("general", "Acme")
        assert set(pols.keys()) == {
            "PRIVACY_POLICY", "REFUND_POLICY",
            "TERMS_OF_SERVICE", "SHIPPING_POLICY",
        }
        for body in pols.values():
            # Each policy has at least a heading and one
            # paragraph
            assert "<h1>" in body
            assert "<p>" in body

    def test_store_name_appears_in_bodies(self):
        from execution.store_configurator import (
            _policy_templates,
        )
        pols = _policy_templates("general", "Acme Inc")
        for body in pols.values():
            # Store name OR derived email appears
            assert (
                "Acme Inc" in body
                or "acmeinc" in body
            )

    def test_empty_store_name_falls_back(self):
        from execution.store_configurator import (
            _policy_templates,
        )
        pols = _policy_templates("general", "")
        assert "Our Store" in pols["PRIVACY_POLICY"]
