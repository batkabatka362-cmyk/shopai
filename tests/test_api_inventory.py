"""Tests for engines.api_inventory -- W963-98."""
from __future__ import annotations

from engines.api_inventory import ApiInventoryEngine
from engines.api_inventory.inventory import (
    AliasStatus,
    CategoryReport,
    InventoryReport,
    ALIAS_ROLES,
    CATEGORIES,
    build_inventory,
)


# ── build_inventory ───────────────────────────────────────


class TestBuildInventory:
    def test_returns_categories_in_priority_order(self):
        r = build_inventory(
            env_aliases_override={
                "shopify_url": "SHOPAI_SHOPIFY_URL",
                "shopify_key": "SHOPAI_SHOPIFY_KEY",
                "openai":      "OPENAI_API_KEY",
            },
            configured_aliases_override=[],
        )
        priorities = [c.priority for c in r.categories]
        assert priorities == sorted(priorities)
        # shopify should be first (priority=1)
        assert r.categories[0].key == "shopify"

    def test_all_unset_blocks_launch(self):
        r = build_inventory(
            env_aliases_override={
                "shopify_url": "SHOPAI_SHOPIFY_URL",
                "shopify_key": "SHOPAI_SHOPIFY_KEY",
            },
            configured_aliases_override=[],
        )
        assert r.ready_for_launch is False
        # Should suggest setting the shopify creds
        assert "shopify" in r.headline.lower() or \
               "shopify" in r.next_action.lower()

    def test_shopify_minimum_met_when_both_set(self):
        r = build_inventory(
            env_aliases_override={
                "shopify_url": "SHOPAI_SHOPIFY_URL",
                "shopify_key": "SHOPAI_SHOPIFY_KEY",
            },
            configured_aliases_override=[
                "shopify_url", "shopify_key",
            ],
        )
        shopify_cat = next(
            c for c in r.categories if c.key == "shopify"
        )
        assert shopify_cat.status == "ready"
        assert shopify_cat.configured_count == 2

    def test_brain_minimum_met_with_one_key(self):
        """brain has minimum=1; any LLM key satisfies."""
        r = build_inventory(
            env_aliases_override={
                "openai":    "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
            },
            configured_aliases_override=["openai"],
        )
        brain_cat = next(
            c for c in r.categories if c.key == "brain"
        )
        assert brain_cat.status == "ready"
        assert brain_cat.configured_count == 1

    def test_optional_categories_marked_optional_when_empty(
        self,
    ):
        """A category with minimum=0 and no aliases set is
        'optional' (not 'incomplete')."""
        r = build_inventory(
            env_aliases_override={
                "judgeme": "JUDGEME_API_TOKEN",
            },
            configured_aliases_override=[],
        )
        reviews_cat = next(
            c for c in r.categories if c.key == "reviews"
        )
        # Reviews has minimum=0
        assert reviews_cat.minimum == 0
        assert reviews_cat.status == "optional"

    def test_uncategorised_alias_lands_in_other(self):
        r = build_inventory(
            env_aliases_override={
                "totally_made_up_alias": "FAKE_ENV_VAR",
            },
            configured_aliases_override=[],
        )
        other_cats = [
            c for c in r.categories if c.key == "other"
        ]
        assert len(other_cats) == 1
        assert any(
            a.alias == "totally_made_up_alias"
            for a in other_cats[0].aliases
        )

    def test_alias_status_carries_env_var(self):
        r = build_inventory(
            env_aliases_override={
                "shopify_url": "SHOPAI_SHOPIFY_URL",
            },
            configured_aliases_override=[],
        )
        shopify_cat = next(
            c for c in r.categories if c.key == "shopify"
        )
        assert shopify_cat.aliases[0].env_var == \
            "SHOPAI_SHOPIFY_URL"

    def test_next_action_suggests_missing_env_var(self):
        """When shopify is missing, next_action mentions
        the env var name so operator can copy/paste."""
        r = build_inventory(
            env_aliases_override={
                "shopify_url": "SHOPAI_SHOPIFY_URL",
                "shopify_key": "SHOPAI_SHOPIFY_KEY",
            },
            configured_aliases_override=[],
        )
        # Top blocker is shopify
        assert "SHOPAI_SHOPIFY" in r.next_action

    def test_configured_aliases_sort_to_back(self):
        """Within a category, unset aliases come first
        (operator sees what to fix at the top)."""
        r = build_inventory(
            env_aliases_override={
                "shopify_url": "SHOPAI_SHOPIFY_URL",
                "shopify_key": "SHOPAI_SHOPIFY_KEY",
            },
            configured_aliases_override=["shopify_url"],
        )
        shopify_cat = next(
            c for c in r.categories if c.key == "shopify"
        )
        # First alias should be the un-configured one
        assert shopify_cat.aliases[0].configured is False
        assert shopify_cat.aliases[1].configured is True


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = ApiInventoryEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert "error" in r

    def test_none_success(self):
        r = ApiInventoryEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = ApiInventoryEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = ApiInventoryEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = ApiInventoryEngine().run({})
        assert r["meta"]["engine"] == "api_inventory"

    def test_data_has_categories(self):
        r = ApiInventoryEngine().run({})
        assert "categories" in r["data"]
        assert isinstance(r["data"]["categories"], list)
        assert r["data"]["total_aliases"] > 0

    def test_data_has_headline_and_next_action(self):
        r = ApiInventoryEngine().run({})
        assert r["data"]["headline"]
        assert r["data"]["next_action"]


# ── Catalog sanity ────────────────────────────────────────


class TestCatalogSanity:
    def test_every_alias_in_roles_dict(self):
        """ALIAS_ROLES should cover every alias that the
        production registry knows about. Lets us catch
        drift -- new adapter added to core.adapters.config
        without a role assignment."""
        from core.adapters.config import ENV_ALIASES
        missing = [
            a for a in ENV_ALIASES
            if a not in ALIAS_ROLES
        ]
        # Any alias not categorised falls into "other"
        # bucket -- not a fatal error but worth surfacing.
        # We assert <=5 uncategorised so a future PR can
        # add 1-2 without breaking the test, but a wave of
        # new adapters triggers a flag.
        assert len(missing) <= 5, (
            f"Uncategorised aliases (add to ALIAS_ROLES): "
            f"{missing}"
        )

    def test_every_role_category_in_categories_list(self):
        """Every category key referenced in ALIAS_ROLES
        must have a metadata entry in CATEGORIES."""
        cat_keys = {c["key"] for c in CATEGORIES}
        role_cats = {v[0] for v in ALIAS_ROLES.values()}
        missing = role_cats - cat_keys
        assert not missing, (
            f"ALIAS_ROLES uses categories not in "
            f"CATEGORIES: {missing}"
        )

    def test_priority_unique(self):
        prios = [c["priority"] for c in CATEGORIES]
        assert len(prios) == len(set(prios))
