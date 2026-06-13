"""Tests for arm_recommender engine→domain mapping (W963-82)."""
from __future__ import annotations

from engines.agi_arm_recommender.engine_domain_mapping import (
    domains_used,
    engine_to_domain,
    engines_with_autonomy_domain,
)


class TestEngineToDomain:
    def test_spend_engines_map_to_marketing(self):
        for eng in (
            "ads_launcher",
            "pinterest_publisher",
            "instagram_publisher",
            "tiktok_publisher",
        ):
            assert engine_to_domain(eng) == "marketing", (
                f"{eng} should map to marketing"
            )

    def test_refund_applier_maps_to_customer_support(self):
        assert engine_to_domain("refund_applier") == (
            "customer_support"
        )

    def test_discount_cleanup_self_maps(self):
        assert engine_to_domain("discount_cleanup") == (
            "discount_cleanup"
        )

    def test_revenue_engines_have_none(self):
        for eng in (
            "loyalty",
            "cart_recovery",
            "email_marketing",
            "affiliate",
            "browse_recovery",
            "welcome_series",
            "churn_prediction",
            "review_request",
        ):
            assert engine_to_domain(eng) is None, (
                f"{eng} should map to None (no autonomy "
                "substrate)"
            )

    def test_exploration_engines_have_none(self):
        for eng in (
            "transfer_scan",
            "content_publisher",
            "product_sourcer",
            "blog_post_generator",
        ):
            assert engine_to_domain(eng) is None

    def test_unknown_engine_returns_none(self):
        assert engine_to_domain("does_not_exist") is None
        assert engine_to_domain("") is None


# ── domains_used ──────────────────────────────────────────


class TestDomainsUsed:
    def test_returns_real_autonomy_domains(self):
        """Domains returned should match the actual
        DOMAIN_APPLY_FLAGS catalog so disarm() doesn't
        ValueError."""
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS,
        )
        for dom in domains_used():
            assert dom in DOMAIN_APPLY_FLAGS, (
                f"{dom} maps to nothing in "
                "DOMAIN_APPLY_FLAGS"
            )

    def test_marketing_is_in_set(self):
        assert "marketing" in domains_used()

    def test_no_duplicates(self):
        domains = domains_used()
        assert len(domains) == len(set(domains))


# ── engines_with_autonomy_domain ──────────────────────────


class TestEnginesWithAutonomyDomain:
    def test_only_includes_mapped_engines(self):
        eng_list = engines_with_autonomy_domain()
        for eng in eng_list:
            assert engine_to_domain(eng) is not None

    def test_excludes_none_mapped(self):
        eng_list = engines_with_autonomy_domain()
        assert "loyalty" not in eng_list
        assert "transfer_scan" not in eng_list

    def test_includes_spend_engines(self):
        eng_list = engines_with_autonomy_domain()
        assert "ads_launcher" in eng_list
        assert "pinterest_publisher" in eng_list


# ── Integration: recommender output -> mapping ────────────


class TestRecommenderToMapping:
    def test_attributed_loss_disarm_engines_all_map_or_none(self):
        """The arm_recommender's attributed_loss DISARM
        recommendations should each map to a real domain
        or None (never raise / never produce a bogus domain
        name)."""
        from engines.agi_arm_recommender.recommender import (
            recommend,
        )
        r = recommend(
            signals_override={
                "verdict": "attributed_loss",
                "trajectory": "flat",
            },
        )
        for rec in r.disarm_recommendations:
            dom = engine_to_domain(rec.engine)
            # Either maps or None (skipped) -- never an
            # invalid domain
            if dom is not None:
                from core.automation.autonomy_armed \
                    import DOMAIN_APPLY_FLAGS
                assert dom in DOMAIN_APPLY_FLAGS

    def test_critical_streak_disarm_engines_map_safely(self):
        from engines.agi_arm_recommender.recommender import (
            recommend,
        )
        r = recommend(
            signals_override={
                "verdict": "earning",
                "trajectory": "flat",
                "streak_top": "loss_streak",
                "streak_severity": "critical",
            },
        )
        for rec in r.disarm_recommendations:
            dom = engine_to_domain(rec.engine)
            if dom is not None:
                from core.automation.autonomy_armed \
                    import DOMAIN_APPLY_FLAGS
                assert dom in DOMAIN_APPLY_FLAGS
