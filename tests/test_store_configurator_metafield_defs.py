"""StoreConfigurator product metafield definitions tests (Phase 2f).

Creates 5 typed definitions (warranty / materials /
care_instructions / country_of_origin / video_url) on the
PRODUCT ownerType. Compounds with Phase 2a brand metafields
for a fully-structured storefront.
"""
from __future__ import annotations


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(
    monkeypatch,
    graphql_responses=None,
    track_calls=None,
):
    track_calls = (
        track_calls if track_calls is not None else []
    )
    responses = list(graphql_responses or [])

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            pass

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return {}

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return {}

        def put(self, path, *, json=None):
            return {}

        def delete(self, path):
            return {}

        def graphql(self, query, variables=None):
            track_calls.append((
                "GRAPHQL", query[:40], variables,
            ))
            if responses:
                return responses.pop(0)
            # Default: created
            return {
                "data": {
                    "metafieldDefinitionCreate": {
                        "createdDefinition": {
                            "id": "gid://shopify/MFD/1",
                            "name": variables[
                                "definition"
                            ]["name"],
                            "key": variables[
                                "definition"
                            ]["key"],
                            "namespace": "custom",
                            "type": {
                                "name": variables[
                                    "definition"
                                ]["type"],
                            },
                        },
                        "userErrors": [],
                    },
                },
            }

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )
    return track_calls


class TestMetafieldDefsFeatureEnabled:
    def test_feature_in_all(self):
        from execution.store_configurator import ALL_FEATURES
        assert "metafield_definitions" in ALL_FEATURES


class TestMetafieldDefsDryRun:
    def test_plan_entries_recorded(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["metafield_definitions"],
        )
        md = result["results"]["metafield_definitions"]
        assert md["status"] == "dry_run"
        assert set(md["created"]) == {
            "warranty", "materials", "care_instructions",
            "country_of_origin", "video_url",
        }

    def test_plan_includes_all_five(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["metafield_definitions"],
        )
        plan_entries = [
            e for e in result["plan"]
            if e.get("action")
            == "create_metafield_definition"
        ]
        assert len(plan_entries) == 5


class TestMetafieldDefsLive:
    def test_all_created(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["metafield_definitions"],
        )
        graphql_calls = [
            c for c in calls if c[0] == "GRAPHQL"
        ]
        assert len(graphql_calls) == 5
        md = result["results"]["metafield_definitions"]
        assert md["status"] == "success"
        assert len(md["created"]) == 5

    def test_taken_classified_as_existing(
        self, monkeypatch,
    ):
        """Re-running the configurator should be idempotent —
        Shopify returns userErrors.code=TAKEN which we
        translate into the `existing` bucket."""
        _install_fake_client(
            monkeypatch,
            graphql_responses=[
                {
                    "data": {
                        "metafieldDefinitionCreate": {
                            "createdDefinition": None,
                            "userErrors": [
                                {
                                    "field": ["key"],
                                    "message": "key already taken",
                                    "code": "TAKEN",
                                },
                            ],
                        },
                    },
                },
            ] * 5,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["metafield_definitions"],
        )
        md = result["results"]["metafield_definitions"]
        assert len(md["existing"]) == 5
        assert md["created"] == []
        assert md["errors"] == []
        # Status is "success" because errors is empty (TAKEN
        # is idempotent, not a failure)
        assert md["status"] == "success"

    def test_other_user_errors_recorded(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            graphql_responses=[
                {
                    "data": {
                        "metafieldDefinitionCreate": {
                            "createdDefinition": None,
                            "userErrors": [
                                {
                                    "field": ["name"],
                                    "message": "name too long",
                                    "code": "INVALID",
                                },
                            ],
                        },
                    },
                },
            ] * 5,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["metafield_definitions"],
        )
        md = result["results"]["metafield_definitions"]
        assert md["status"] == "partial"
        assert len(md["errors"]) == 5

    def test_transport_error_isolated_per_definition(
        self, monkeypatch,
    ):
        """One definition failing transport doesn't block
        the others."""
        _install_fake_client(
            monkeypatch,
            graphql_responses=[
                # 1st OK
                {
                    "data": {
                        "metafieldDefinitionCreate": {
                            "createdDefinition": {
                                "id": "1",
                                "name": "Warranty",
                                "key": "warranty",
                                "namespace": "custom",
                                "type": {
                                    "name": "single_line_text_field",
                                },
                            },
                            "userErrors": [],
                        },
                    },
                },
                # 2nd fails
                {"error": "rate limited"},
                # 3rd, 4th, 5th OK
                *([
                    {
                        "data": {
                            "metafieldDefinitionCreate": {
                                "createdDefinition": {
                                    "id": "x", "name": "x",
                                    "key": "x",
                                    "namespace": "custom",
                                    "type": {"name": "x"},
                                },
                                "userErrors": [],
                            },
                        },
                    },
                ] * 3),
            ],
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["metafield_definitions"],
        )
        md = result["results"]["metafield_definitions"]
        assert len(md["created"]) == 4
        assert len(md["errors"]) == 1
