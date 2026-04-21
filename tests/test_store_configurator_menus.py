"""StoreConfigurator menus feature tests (Phase 1b).

Uses the GraphQL helper to update the two default Shopify
menus (main-menu + footer) with niche-aware items. These are
the navigation a shopper sees on every page.
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
    """Graphql-aware fake client.

    ``graphql_responses`` is a list of responses returned in
    order for each .graphql() call. If None, the fake returns
    generic success shapes for menus query + menuUpdate.
    """
    track_calls = (
        track_calls if track_calls is not None else []
    )
    responses = list(graphql_responses or [])

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            self.shop_url = shop_url

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return {}

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return {}

        def put(self, path, *, json=None):
            track_calls.append(("PUT", path, json))
            return {}

        def delete(self, path):
            track_calls.append(("DELETE", path, None))
            return {}

        def graphql(self, query, variables=None):
            track_calls.append((
                "GRAPHQL", query[:30], variables,
            ))
            if responses:
                return responses.pop(0)
            if "menus(first" in query:
                return {
                    "data": {
                        "menus": {
                            "nodes": [
                                {
                                    "id": "gid://shopify/Menu/1",
                                    "handle": "main-menu",
                                    "title": "Main menu",
                                },
                                {
                                    "id": "gid://shopify/Menu/2",
                                    "handle": "footer",
                                    "title": "Footer",
                                },
                            ],
                        },
                    },
                }
            # menuUpdate
            return {
                "data": {
                    "menuUpdate": {
                        "menu": {
                            "id": (
                                variables["id"]
                                if variables else "?"
                            ),
                            "handle": (
                                variables.get("handle", "?")
                                if variables else "?"
                            ),
                            "title": (
                                variables.get("title", "?")
                                if variables else "?"
                            ),
                            "items": [],
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


class TestMenusFeatureEnabled:
    def test_menus_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "menus" in ALL_FEATURES


class TestMenusDryRun:
    def test_both_menus_planned(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="fashion",
            features=["menus"],
        )
        menus = result["results"]["menus"]
        assert menus["status"] == "dry_run"
        assert set(menus["updated"]) == {"main-menu", "footer"}
        assert menus["errors"] == []

    def test_plan_entries_recorded(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["menus"],
        )
        menu_plan = [
            e for e in result["plan"]
            if e.get("action") == "update_menu"
        ]
        assert len(menu_plan) == 2
        handles = {e["handle"] for e in menu_plan}
        assert handles == {"main-menu", "footer"}


class TestMenusLive:
    def test_two_menuupdate_calls(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="tech",
            features=["menus"],
        )
        # 1 list query + 2 update calls = 3 graphql
        graphql_calls = [
            c for c in calls if c[0] == "GRAPHQL"
        ]
        assert len(graphql_calls) == 3
        updates = [
            c for c in graphql_calls
            if c[2] and "id" in (c[2] or {})
        ]
        assert len(updates) == 2
        menus_out = result["results"]["menus"]
        assert menus_out["status"] == "success"
        assert set(menus_out["updated"]) == {
            "main-menu", "footer",
        }

    def test_menu_items_reach_mutation(self, monkeypatch):
        """Verify niche-specific items actually flow into the
        menuUpdate variables (not dropped between template +
        call)."""
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=False)
        c.configure(
            "x.myshopify.com", "tok",
            niche="home",
            features=["menus"],
        )
        main_menu_call = next(
            call for call in calls
            if call[0] == "GRAPHQL"
            and call[2]
            and call[2].get("handle") == "main-menu"
        )
        items = main_menu_call[2]["items"]
        titles = [i["title"] for i in items]
        # Home niche puts "Shop Home" in main menu
        assert "Shop Home" in titles
        assert "About" in titles

    def test_missing_menu_recorded_as_error(self, monkeypatch):
        """If Shopify doesn't return a menu with our handle
        (never happens on standard stores but defensible),
        treat it as a structured error."""
        _install_fake_client(
            monkeypatch,
            graphql_responses=[
                # menus query — only main-menu, no footer
                {
                    "data": {
                        "menus": {
                            "nodes": [
                                {
                                    "id": "gid://1",
                                    "handle": "main-menu",
                                    "title": "Main",
                                },
                            ],
                        },
                    },
                },
                # menuUpdate for main-menu
                {
                    "data": {
                        "menuUpdate": {
                            "menu": {
                                "id": "gid://1",
                                "handle": "main-menu",
                                "title": "Main",
                                "items": [],
                            },
                            "userErrors": [],
                        },
                    },
                },
            ],
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["menus"],
        )
        menus_out = result["results"]["menus"]
        assert menus_out["status"] == "partial"
        assert "main-menu" in menus_out["updated"]
        err_handles = {
            e["handle"] for e in menus_out["errors"]
        }
        assert "footer" in err_handles

    def test_graphql_user_errors_recorded(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            graphql_responses=[
                # menus query
                {
                    "data": {
                        "menus": {
                            "nodes": [
                                {
                                    "id": "gid://1",
                                    "handle": "main-menu",
                                    "title": "M",
                                },
                                {
                                    "id": "gid://2",
                                    "handle": "footer",
                                    "title": "F",
                                },
                            ],
                        },
                    },
                },
                # menuUpdate #1 — userErrors
                {
                    "data": {
                        "menuUpdate": {
                            "menu": None,
                            "userErrors": [
                                {
                                    "field": "items",
                                    "message": "invalid",
                                },
                            ],
                        },
                    },
                },
                # menuUpdate #2 — userErrors
                {
                    "data": {
                        "menuUpdate": {
                            "menu": None,
                            "userErrors": [
                                {
                                    "field": "title",
                                    "message": "too long",
                                },
                            ],
                        },
                    },
                },
            ],
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["menus"],
        )
        menus_out = result["results"]["menus"]
        assert menus_out["status"] == "error"
        assert menus_out["updated"] == []
        msgs = [e["error"] for e in menus_out["errors"]]
        assert any("invalid" in m for m in msgs)
        assert any("too long" in m for m in msgs)

    def test_list_query_error_bails_whole_feature(
        self, monkeypatch,
    ):
        _install_fake_client(
            monkeypatch,
            graphql_responses=[
                {"error": "rate limited"},
            ],
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["menus"],
        )
        menus_out = result["results"]["menus"]
        assert menus_out["status"] == "error"
        assert menus_out["updated"] == []
        assert menus_out["errors"][0]["handle"] == "*"


class TestMenuTemplates:
    def test_main_and_footer_keys(self):
        from execution.store_configurator import (
            _menu_items_for_niche,
        )
        plan = _menu_items_for_niche("general")
        assert set(plan.keys()) == {"main-menu", "footer"}

    def test_fashion_niche_shows_new_arrivals(self):
        from execution.store_configurator import (
            _menu_items_for_niche,
        )
        plan = _menu_items_for_niche("fashion")
        titles = [i["title"] for i in plan["main-menu"]]
        assert "New Arrivals" in titles

    def test_footer_has_policy_links(self):
        from execution.store_configurator import (
            _menu_items_for_niche,
        )
        plan = _menu_items_for_niche("general")
        footer_urls = {
            i["url"] for i in plan["footer"]
        }
        for u in (
            "/policies/privacy-policy",
            "/policies/refund-policy",
            "/policies/shipping-policy",
            "/policies/terms-of-service",
        ):
            assert u in footer_urls
