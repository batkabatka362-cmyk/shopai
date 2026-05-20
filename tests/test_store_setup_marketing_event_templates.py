"""Tests for
``engines.store_setup.marketing_event_templates``.

Generator produces niche-aware launch campaign specs;
handoff helper translates to per-campaign kwargs for
``SHOPIFY_CREATE_MARKETING_ACTIVITY``.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: every niche has 5+ campaigns (5 universals
     + niche-specific).
  3. Generator: each campaign has full shape.
  4. Generator: every niche resolves.
  5. Generator: title prefixed with store_name.
  6. Generator: status defaults to paused; can override
     to active; invalid value -> paused.
  7. Generator: utm_campaign carries niche suffix.
  8. Generator: niche-specific campaigns surface (Pinterest
     for beauty / home / jewelry / baby; YouTube for
     fitness + outdoor; etc.)
  9. Generator: budget_daily_usd is float; zero for free
     campaigns (email).
 10. Handoff: produces per-campaign kwargs dict.
 11. Handoff: budget included only when > 0.
 12. Handoff: utm.source/medium/campaign structure.
 13. Handoff: remote_url placeholder present (Pattern C
     requirement).
 14. Handoff: empty template -> empty list.
"""
from __future__ import annotations

from engines.store_setup.marketing_event_templates import (
    _NICHE_CAMPAIGNS,
    _UNIVERSAL_CAMPAIGNS,
    generate_marketing_event_templates,
    hand_off_to_marketing_adapter,
)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_marketing_event_templates(
            store_name="",
        ) == {}
        assert generate_marketing_event_templates(
            store_name="   ",
        ) == {}
        assert generate_marketing_event_templates(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_every_niche_has_at_least_universals(self):
        """Every niche carries the 5 universal campaigns
        + 0-3 niche-specific."""
        universal_count = len(_UNIVERSAL_CAMPAIGNS)
        for niche in _NICHE_CAMPAIGNS:
            spec = generate_marketing_event_templates(
                store_name="Acme", niche=niche,
            )
            assert (
                len(spec["campaigns"])
                >= universal_count
            ), niche

    def test_every_campaign_has_full_shape(self):
        for niche in _NICHE_CAMPAIGNS:
            spec = generate_marketing_event_templates(
                store_name="Acme", niche=niche,
            )
            for c in spec["campaigns"]:
                assert c["name"], niche
                assert c["title"], niche
                assert c["channel"], niche
                assert c["tactic"], niche
                assert c["status"], niche
                assert c["utm_source"], niche
                assert c["utm_medium"], niche
                assert c["utm_campaign"], niche
                assert isinstance(
                    c["budget_daily_usd"], float,
                )
                assert c["rationale"], niche
                assert c["when_to_launch"], niche

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_marketing_event_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["campaigns"]

    def test_title_prefixed_with_store(self):
        spec = generate_marketing_event_templates(
            store_name="Acme Beauty", niche="beauty",
        )
        for c in spec["campaigns"]:
            assert c["title"].startswith("Acme Beauty -- ")

    def test_utm_campaign_carries_niche_suffix(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", niche="beauty",
        )
        for c in spec["campaigns"]:
            assert c["utm_campaign"].endswith("_beauty"), (
                c["utm_campaign"]
            )


class TestStatusDefault:

    def test_default_status_paused(self):
        spec = generate_marketing_event_templates(
            store_name="Acme",
        )
        for c in spec["campaigns"]:
            assert c["status"] == "paused"

    def test_override_to_active(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", create_status="active",
        )
        for c in spec["campaigns"]:
            assert c["status"] == "active"

    def test_invalid_status_falls_back_to_paused(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", create_status="ufo",
        )
        for c in spec["campaigns"]:
            assert c["status"] == "paused"


class TestNicheSpecific:

    def test_beauty_has_pinterest(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", niche="beauty",
        )
        names = {c["name"] for c in spec["campaigns"]}
        assert any("Pinterest" in n for n in names)

    def test_food_has_subscribe_save(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", niche="food",
        )
        names = {c["name"] for c in spec["campaigns"]}
        assert any("Subscribe" in n for n in names)

    def test_fitness_has_youtube(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", niche="fitness",
        )
        names = {c["name"] for c in spec["campaigns"]}
        assert any("YouTube" in n for n in names)

    def test_jewelry_has_bridal(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", niche="jewelry",
        )
        names = {c["name"] for c in spec["campaigns"]}
        assert any(
            "Bridal" in n or "Editorial" in n
            for n in names
        )

    def test_baby_has_age_stage(self):
        spec = generate_marketing_event_templates(
            store_name="Acme", niche="baby",
        )
        names = {c["name"] for c in spec["campaigns"]}
        assert any("Age-Stage" in n for n in names)


class TestBudgets:

    def test_email_campaigns_have_zero_budget(self):
        """Email campaigns are free to run -- budget
        should be 0."""
        spec = generate_marketing_event_templates(
            store_name="Acme",
        )
        email_campaigns = [
            c for c in spec["campaigns"]
            if c["channel"] in ("email",)
        ]
        assert len(email_campaigns) >= 1
        for c in email_campaigns:
            assert c["budget_daily_usd"] == 0.0

    def test_paid_campaigns_have_positive_budget(self):
        spec = generate_marketing_event_templates(
            store_name="Acme",
        )
        paid_tactics = {"ad", "search", "retargeting"}
        paid_campaigns = [
            c for c in spec["campaigns"]
            if c["tactic"] in paid_tactics
        ]
        assert len(paid_campaigns) >= 3
        for c in paid_campaigns:
            assert c["budget_daily_usd"] > 0


# ── Handoff ──────────────────────────────────────────────────


class TestHandoff:

    def test_produces_per_campaign_kwargs(self):
        template = generate_marketing_event_templates(
            store_name="Acme", niche="beauty",
        )
        kwargs_list = hand_off_to_marketing_adapter(
            template,
        )
        assert (
            len(kwargs_list) == len(template["campaigns"])
        )
        for k in kwargs_list:
            assert "title" in k
            assert "channel" in k
            assert "tactic" in k
            assert "status" in k
            assert "utm" in k
            assert "remote_url" in k

    def test_utm_nested(self):
        template = generate_marketing_event_templates(
            store_name="Acme",
        )
        kwargs_list = hand_off_to_marketing_adapter(
            template,
        )
        for k in kwargs_list:
            assert "source" in k["utm"]
            assert "medium" in k["utm"]
            assert "campaign" in k["utm"]

    def test_budget_only_when_positive(self):
        template = generate_marketing_event_templates(
            store_name="Acme",
        )
        kwargs_list = hand_off_to_marketing_adapter(
            template,
        )
        # Find email campaigns -- they have budget 0 in
        # the template, so no budget key in the kwargs.
        for original, kwargs in zip(
            template["campaigns"], kwargs_list,
        ):
            if original["budget_daily_usd"] == 0:
                assert "budget" not in kwargs
            else:
                assert "budget" in kwargs
                assert kwargs["budget"]["currency_code"] == (
                    "USD"
                )

    def test_remote_url_placeholder_present(self):
        """Pattern C: marketingActivityCreateExternal
        requires remote_url. Even though the operator
        hasn't created the real campaign yet, we ship a
        placeholder so the adapter accepts the call."""
        template = generate_marketing_event_templates(
            store_name="Acme",
        )
        kwargs_list = hand_off_to_marketing_adapter(
            template,
        )
        for k in kwargs_list:
            assert k["remote_url"].startswith(
                "https://",
            )

    def test_empty_template(self):
        assert hand_off_to_marketing_adapter({}) == []
        assert hand_off_to_marketing_adapter(None) == []  # type: ignore[arg-type]
        assert hand_off_to_marketing_adapter(
            {"store_name": "Acme"},
        ) == []
