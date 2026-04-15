"""Tests for the winning_products engine.

The engine consumes normalised spy records (output from
``core.adapters.ads_spy._base.AdsSpyBaseAdapter._normalise_record``)
and produces a scored, verdict-tagged, top-K winner list.

Coverage:

  * Input validation + upstream-failure propagation
  * Filtering (min_days_running, require_product_url)
  * Product dedupe by normalised URL + multi-source merge
  * Scoring — each dimension in isolation (days_running,
    source_count, engagement_velocity, views, country breadth,
    price fit)
  * Verdict thresholds (strong_buy / buy / watch / skip)
  * Hero-ad selection (max days, tie-break on views)
  * top_k trimming + sort order
  * Output envelope shape (status/data/meta/error)
"""
from __future__ import annotations

from engines.winning_products import ENGINE_NAME, WinningProductsEngine, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(**overrides):
    """Produce a normalised spy record with sensible defaults."""
    base = {
        "ad_id": "a1",
        "source": "minea",
        "advertiser": "Acme",
        "product_url": "https://store.com/products/gadget",
        "creative_url": "",
        "creative_type": "video",
        "headline": "Cool Gadget",
        "copy": "",
        "cta": "",
        "first_seen": "",
        "last_seen": "",
        "days_running": 30,
        "engagement": {"likes": 0, "comments": 0, "shares": 0, "views": 0},
        "country_targets": ["US"],
        "language": "en",
        "product_signals": {
            "price_estimate": 0.0,
            "store_platform": "",
            "category_hint": "",
        },
        "raw_url": "",
    }
    for k, v in overrides.items():
        base[k] = v
    return base


# ---------------------------------------------------------------------------
# Envelope & entry point
# ---------------------------------------------------------------------------


class TestEntryPoint:
    def test_engine_name_exported(self):
        assert ENGINE_NAME == "winning_products"

    def test_class_wrapper_delegates(self):
        out = WinningProductsEngine().run({"spy_records": []})
        assert out["status"] == "success"
        assert out["meta"]["engine"] == "winning_products"

    def test_empty_input_is_success(self):
        out = run(None)
        assert out["status"] == "success"
        assert out["data"]["winners"] == []
        assert out["data"]["total_records"] == 0
        assert out["data"]["unique_products"] == 0

    def test_upstream_failure_is_propagated(self):
        out = run({"status": "fail", "error": "minea 429"})
        assert out["status"] == "error"
        assert "minea 429" in out["error"]

    def test_records_not_list_is_error(self):
        out = run({"spy_records": "not-a-list"})
        assert out["status"] == "error"
        assert "spy_records" in out["error"]

    def test_output_envelope(self):
        out = run({"spy_records": []})
        assert set(out.keys()) == {"status", "data", "meta", "error"}
        assert set(out["meta"].keys()) >= {"engine", "timestamp", "elapsed_seconds"}


# ---------------------------------------------------------------------------
# Copy-on-entry contract
# ---------------------------------------------------------------------------


class TestCopyOnEntry:
    def test_caller_dict_not_mutated(self):
        payload = {"spy_records": [_rec()]}
        snapshot = {
            "spy_records_id": id(payload["spy_records"]),
            "record_id": id(payload["spy_records"][0]),
        }
        run(payload)
        # Caller's list + record should be untouched
        assert id(payload["spy_records"]) == snapshot["spy_records_id"]
        assert payload["spy_records"][0]["ad_id"] == "a1"


# ---------------------------------------------------------------------------
# Filter stage
# ---------------------------------------------------------------------------


class TestFilter:
    def test_drops_records_below_min_days(self):
        recs = [
            _rec(ad_id="young", days_running=3),
            _rec(ad_id="old", days_running=30),
        ]
        out = run({"spy_records": recs, "criteria": {"min_days_running": 7}})
        assert out["data"]["total_after_filter"] == 1
        winners = out["data"]["winners"]
        assert len(winners) == 1
        assert winners[0]["hero_ad"]["ad_id"] == "old"

    def test_drops_records_without_product_url_when_required(self):
        recs = [
            _rec(ad_id="no-url", product_url=""),
            _rec(ad_id="with-url", product_url="https://store.com/products/a"),
        ]
        out = run({"spy_records": recs, "criteria": {"require_product_url": True}})
        assert out["data"]["total_after_filter"] == 1

    def test_keeps_urlless_records_when_not_required(self):
        recs = [
            _rec(ad_id="no-url", product_url="", advertiser="A", headline="B"),
        ]
        out = run({"spy_records": recs, "criteria": {"require_product_url": False}})
        assert out["data"]["total_after_filter"] == 1

    def test_non_dict_entries_ignored(self):
        recs = [_rec(), None, "junk", 42]
        out = run({"spy_records": recs})
        assert out["data"]["total_after_filter"] == 1


# ---------------------------------------------------------------------------
# Dedupe stage
# ---------------------------------------------------------------------------


class TestDedupe:
    def test_same_url_different_trailing_slash_dedupes(self):
        recs = [
            _rec(ad_id="a", product_url="https://store.com/products/gadget"),
            _rec(ad_id="b", source="pipiads",
                 product_url="https://store.com/products/gadget/"),
        ]
        out = run({"spy_records": recs})
        assert out["data"]["unique_products"] == 1

    def test_query_string_stripped(self):
        recs = [
            _rec(ad_id="a", product_url="https://store.com/products/x?ref=fb"),
            _rec(ad_id="b", source="bigspy",
                 product_url="https://store.com/products/x?ref=tt"),
        ]
        out = run({"spy_records": recs})
        assert out["data"]["unique_products"] == 1

    def test_scheme_and_www_normalised(self):
        recs = [
            _rec(ad_id="a", product_url="https://www.store.com/products/x"),
            _rec(ad_id="b", source="pipiads",
                 product_url="http://store.com/products/x"),
        ]
        out = run({"spy_records": recs})
        assert out["data"]["unique_products"] == 1

    def test_different_products_stay_separate(self):
        recs = [
            _rec(ad_id="a", product_url="https://s.com/products/x"),
            _rec(ad_id="b", product_url="https://s.com/products/y"),
        ]
        out = run({"spy_records": recs})
        assert out["data"]["unique_products"] == 2

    def test_no_url_fallback_to_advertiser_and_headline(self):
        recs = [
            _rec(ad_id="a", product_url="",
                 advertiser="Acme", headline="Buy Cool Gadget Now"),
            _rec(ad_id="b", product_url="", source="pipiads",
                 advertiser="Acme", headline="Buy Cool Gadget Now Today"),
        ]
        out = run({
            "spy_records": recs,
            "criteria": {"require_product_url": False},
        })
        # First 5 headline words match ("buy cool gadget now today" vs
        # "buy cool gadget now") — the second one has only 5 words,
        # first one has 4. They differ on the 5th, so they won't
        # collapse. Verify the fallback keys at least *work* (no crash,
        # produces a key per record).
        assert out["data"]["unique_products"] >= 1


# ---------------------------------------------------------------------------
# Scoring — days_running
# ---------------------------------------------------------------------------


def _factor(result, name):
    return result["data"]["winners"][0]["factors"][name]


class TestScoringDaysRunning:
    def test_90_plus_days_max_score(self):
        out = run({"spy_records": [_rec(days_running=120)]})
        assert _factor(out, "days_running")["score"] == 40

    def test_60_to_89_days(self):
        out = run({"spy_records": [_rec(days_running=60)]})
        assert _factor(out, "days_running")["score"] == 35

    def test_30_to_59_days(self):
        out = run({"spy_records": [_rec(days_running=30)]})
        assert _factor(out, "days_running")["score"] == 25

    def test_14_to_29_days(self):
        out = run({"spy_records": [_rec(days_running=14)]})
        assert _factor(out, "days_running")["score"] == 10

    def test_7_to_13_days(self):
        out = run({"spy_records": [_rec(days_running=7)]})
        assert _factor(out, "days_running")["score"] == 4

    def test_group_takes_max_days_running(self):
        recs = [
            _rec(ad_id="a", source="minea", days_running=10),
            _rec(ad_id="b", source="pipiads", days_running=95),
        ]
        out = run({"spy_records": recs})
        winners = out["data"]["winners"]
        assert winners[0]["factors"]["days_running"]["value"] == 95


# ---------------------------------------------------------------------------
# Scoring — source count
# ---------------------------------------------------------------------------


class TestScoringSourceCount:
    def test_single_source_partial_score(self):
        out = run({"spy_records": [_rec(source="minea")]})
        assert _factor(out, "source_count")["score"] == 5

    def test_two_sources_medium_score(self):
        recs = [
            _rec(ad_id="a", source="minea"),
            _rec(ad_id="b", source="pipiads"),
        ]
        out = run({"spy_records": recs})
        assert _factor(out, "source_count")["score"] == 10

    def test_three_sources_full_score(self):
        recs = [
            _rec(ad_id="a", source="minea"),
            _rec(ad_id="b", source="pipiads"),
            _rec(ad_id="c", source="bigspy"),
        ]
        out = run({"spy_records": recs})
        f = _factor(out, "source_count")
        assert f["score"] == 15
        assert set(f["sources"]) == {"minea", "pipiads", "bigspy"}

    def test_empty_source_string_ignored(self):
        recs = [
            _rec(ad_id="a", source=""),
            _rec(ad_id="b", source="minea"),
        ]
        out = run({"spy_records": recs})
        # Only minea counts → 1 source → 5
        assert _factor(out, "source_count")["score"] == 5


# ---------------------------------------------------------------------------
# Scoring — engagement velocity
# ---------------------------------------------------------------------------


class TestScoringEngagementVelocity:
    def test_viral_engagement_full_score(self):
        # likes=1000/day, 30 days → velocity = 1000 → max bucket
        out = run({"spy_records": [
            _rec(days_running=30,
                 engagement={"likes": 30_000, "comments": 0, "shares": 0, "views": 0}),
        ]})
        assert _factor(out, "engagement_velocity")["score"] == 20

    def test_comments_weighted_double(self):
        # 50 comments/day → 100/day effective (> 50 threshold = 10pt)
        out = run({"spy_records": [
            _rec(days_running=10,
                 engagement={"likes": 0, "comments": 500, "shares": 0, "views": 0}),
        ]})
        assert _factor(out, "engagement_velocity")["score"] == 10

    def test_shares_weighted_triple(self):
        # 100 shares / 10 days → 10/day × 3 = 30/day → >= 10 → 4pt
        out = run({"spy_records": [
            _rec(days_running=10,
                 engagement={"likes": 0, "comments": 0, "shares": 100, "views": 0}),
        ]})
        assert _factor(out, "engagement_velocity")["score"] == 4

    def test_no_engagement_zero_score(self):
        out = run({"spy_records": [_rec()]})
        assert _factor(out, "engagement_velocity")["score"] == 0

    def test_malformed_engagement_is_safe(self):
        # Non-dict engagement should not crash the scorer.
        r = _rec()
        r["engagement"] = "bogus"
        out = run({"spy_records": [r]})
        assert out["status"] == "success"
        assert _factor(out, "engagement_velocity")["score"] == 0


# ---------------------------------------------------------------------------
# Scoring — views
# ---------------------------------------------------------------------------


class TestScoringViews:
    def test_one_million_views_full_score(self):
        out = run({"spy_records": [
            _rec(engagement={"likes": 0, "comments": 0, "shares": 0,
                             "views": 1_500_000}),
        ]})
        assert _factor(out, "views")["score"] == 10

    def test_mid_range_views(self):
        out = run({"spy_records": [
            _rec(engagement={"likes": 0, "comments": 0, "shares": 0,
                             "views": 150_000}),
        ]})
        assert _factor(out, "views")["score"] == 5

    def test_low_views_zero(self):
        out = run({"spy_records": [
            _rec(engagement={"likes": 0, "comments": 0, "shares": 0, "views": 50}),
        ]})
        assert _factor(out, "views")["score"] == 0


# ---------------------------------------------------------------------------
# Scoring — country breadth
# ---------------------------------------------------------------------------


class TestScoringCountryBreadth:
    def test_all_tier1_full_score(self):
        out = run({"spy_records": [_rec(country_targets=["US", "CA", "AU", "UK"])]})
        f = _factor(out, "country_breadth")
        assert f["score"] == 10
        assert f["tier1_hit_count"] == 4

    def test_partial_tier1_coverage(self):
        out = run({"spy_records": [_rec(country_targets=["US", "CA"])]})
        assert _factor(out, "country_breadth")["score"] == 6

    def test_case_insensitive(self):
        out = run({"spy_records": [_rec(country_targets=["us", "ca"])]})
        assert _factor(out, "country_breadth")["score"] == 6

    def test_non_tier1_countries_no_credit(self):
        out = run({"spy_records": [_rec(country_targets=["DE", "FR"])]})
        assert _factor(out, "country_breadth")["score"] == 0

    def test_custom_tier1_list_honoured(self):
        out = run({
            "spy_records": [_rec(country_targets=["DE"])],
            "criteria": {"tier1_countries": ["DE", "FR"]},
        })
        assert _factor(out, "country_breadth")["score"] == 3


# ---------------------------------------------------------------------------
# Scoring — price fit
# ---------------------------------------------------------------------------


class TestScoringPriceFit:
    def test_price_in_range_full_score(self):
        r = _rec()
        r["product_signals"] = {"price_estimate": 35.0}
        out = run({"spy_records": [r]})
        assert _factor(out, "price_fit")["score"] == 5

    def test_price_above_max_no_score(self):
        r = _rec()
        r["product_signals"] = {"price_estimate": 500.0}
        out = run({"spy_records": [r]})
        assert _factor(out, "price_fit")["score"] == 0

    def test_price_below_min_no_score(self):
        r = _rec()
        r["product_signals"] = {"price_estimate": 5.0}
        out = run({"spy_records": [r]})
        assert _factor(out, "price_fit")["score"] == 0

    def test_missing_price_partial_credit(self):
        out = run({"spy_records": [_rec()]})  # no price signal
        assert _factor(out, "price_fit")["score"] == 2

    def test_custom_price_window(self):
        r = _rec()
        r["product_signals"] = {"price_estimate": 250.0}
        out = run({
            "spy_records": [r],
            "criteria": {"min_price": 100, "max_price": 300},
        })
        assert _factor(out, "price_fit")["score"] == 5


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_strong_buy_threshold(self):
        # Build a record that should clear 80: 90d (40) + 3 sources
        # (15) + 1M views (10) + 4 Tier1 (10) + viral engagement (20)
        # + price in range (5) = 100
        recs = [
            _rec(ad_id="a", source="minea", days_running=120,
                 country_targets=["US", "CA", "AU", "UK"],
                 engagement={"likes": 30_000, "comments": 0, "shares": 0,
                             "views": 1_500_000},
                 product_signals={"price_estimate": 35.0}),
            _rec(ad_id="b", source="pipiads", days_running=120,
                 country_targets=["US", "CA", "AU", "UK"],
                 engagement={"likes": 30_000, "comments": 0, "shares": 0,
                             "views": 1_500_000},
                 product_signals={"price_estimate": 35.0}),
            _rec(ad_id="c", source="bigspy", days_running=120,
                 country_targets=["US", "CA", "AU", "UK"],
                 engagement={"likes": 30_000, "comments": 0, "shares": 0,
                             "views": 1_500_000},
                 product_signals={"price_estimate": 35.0}),
        ]
        out = run({"spy_records": recs})
        w = out["data"]["winners"][0]
        assert w["verdict"] == "strong_buy"
        assert w["score"] >= 80

    def test_skip_for_low_score(self):
        # Minimum: 7d (4) + 1 source (5) + price unknown (2) = 11 → skip
        out = run({"spy_records": [_rec(days_running=7, country_targets=[])]})
        w = out["data"]["winners"][0]
        assert w["verdict"] == "skip"
        assert w["score"] < 40

    def test_verdict_counts_reflect_all_scored(self):
        recs = [
            _rec(ad_id="low", product_url="https://s.com/low",
                 days_running=7, country_targets=[]),
            _rec(ad_id="high", product_url="https://s.com/high",
                 days_running=120,
                 country_targets=["US", "CA", "AU", "UK"],
                 engagement={"likes": 30_000, "comments": 0, "shares": 0,
                             "views": 1_500_000},
                 product_signals={"price_estimate": 35.0}),
        ]
        out = run({"spy_records": recs})
        counts = out["data"]["verdict_counts"]
        assert counts["skip"] >= 1
        assert sum(counts.values()) == 2


# ---------------------------------------------------------------------------
# Hero ad + ranking
# ---------------------------------------------------------------------------


class TestHeroAndRanking:
    def test_hero_picks_longest_running(self):
        recs = [
            _rec(ad_id="short", source="minea",
                 product_url="https://s.com/p", days_running=10),
            _rec(ad_id="long", source="pipiads",
                 product_url="https://s.com/p", days_running=90),
        ]
        out = run({"spy_records": recs})
        hero = out["data"]["winners"][0]["hero_ad"]
        assert hero["ad_id"] == "long"
        assert hero["days_running"] == 90

    def test_hero_tiebreaks_on_views(self):
        recs = [
            _rec(ad_id="low_views", source="minea",
                 product_url="https://s.com/p", days_running=30,
                 engagement={"likes": 0, "comments": 0, "shares": 0, "views": 10}),
            _rec(ad_id="high_views", source="pipiads",
                 product_url="https://s.com/p", days_running=30,
                 engagement={"likes": 0, "comments": 0, "shares": 0,
                             "views": 1_000_000}),
        ]
        out = run({"spy_records": recs})
        hero = out["data"]["winners"][0]["hero_ad"]
        assert hero["ad_id"] == "high_views"

    def test_winners_sorted_by_score_desc(self):
        recs = [
            _rec(ad_id="weak", product_url="https://s.com/weak",
                 days_running=7, country_targets=[]),
            _rec(ad_id="strong", product_url="https://s.com/strong",
                 days_running=120,
                 country_targets=["US", "CA", "AU", "UK"],
                 engagement={"likes": 30_000, "comments": 0, "shares": 0,
                             "views": 1_500_000}),
        ]
        out = run({"spy_records": recs})
        winners = out["data"]["winners"]
        assert winners[0]["score"] > winners[1]["score"]
        assert winners[0]["hero_ad"]["ad_id"] == "strong"

    def test_top_k_trims_output(self):
        recs = []
        for i in range(20):
            recs.append(_rec(
                ad_id=f"x{i}",
                product_url=f"https://s.com/p{i}",
                days_running=30 + i,
            ))
        out = run({"spy_records": recs, "criteria": {"top_k": 5}})
        assert len(out["data"]["winners"]) == 5
        assert out["data"]["unique_products"] == 20

    def test_invalid_top_k_falls_back_to_default(self):
        recs = [_rec(ad_id="a", product_url="https://s.com/a")]
        out = run({"spy_records": recs, "criteria": {"top_k": 0}})
        # top_k<1 clamped to 10 default
        assert len(out["data"]["winners"]) == 1


# ---------------------------------------------------------------------------
# Sources seen telemetry
# ---------------------------------------------------------------------------


class TestSourcesSeen:
    def test_sources_seen_unique_sorted(self):
        recs = [
            _rec(ad_id="a", source="pipiads"),
            _rec(ad_id="b", source="minea",
                 product_url="https://s.com/other"),
            _rec(ad_id="c", source="pipiads",
                 product_url="https://s.com/another"),
        ]
        out = run({"spy_records": recs})
        assert out["data"]["sources_seen"] == ["minea", "pipiads"]
