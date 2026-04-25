"""Tests for the budget plan runner.

Covers:
  * Campaign name parsing (shopai:<dec>:<handle>)
  * Purchase action extraction across Meta's taxonomy
  * SKU aggregation when multiple campaigns target one handle
  * ``run_budget_plan`` skips gracefully when:
      - no total budget set
      - router unavailable
      - insights fetch fails
      - no campaigns match the naming pattern
  * Happy path writes a plan JSON + returns a populated report
  * ``list_plans`` returns plans newest-first
  * Autopilot wire exposes ``budget_plan_skus`` on CycleSummary
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from core.engines.budget_buyer.plan_runner import (
    PlanReport, _aggregate_to_skus, _days_from_preset,
    _parse_campaign_name, _purchase_count,
    list_plans, run_budget_plan,
)


# ── Pure parsers ─────────────────────────────────────────


class TestCampaignNameParse:
    def test_publisher_pattern_parsed(self):
        dec, handle = _parse_campaign_name(
            "shopai:abc1234567:galaxy-projector",
        )
        assert dec == "abc1234567"
        assert handle == "galaxy-projector"

    def test_underscore_in_handle(self):
        dec, handle = _parse_campaign_name(
            "shopai:xyz:moon_lamp_v2",
        )
        assert handle == "moon_lamp_v2"

    def test_manual_campaign_rejected(self):
        """Owner-created campaigns that don't follow the
        shopai: prefix should return empty tuple so the runner
        skips them."""
        assert _parse_campaign_name(
            "My Cool Campaign 2026",
        ) == ("", "")

    def test_empty_returns_empty(self):
        assert _parse_campaign_name("") == ("", "")

    def test_malformed_returns_empty(self):
        assert _parse_campaign_name("shopai::") == ("", "")


class TestPurchaseCount:
    def test_meta_purchase_action(self):
        actions = [
            {"action_type": "purchase", "value": "3"},
            {"action_type": "link_click", "value": "100"},
        ]
        assert _purchase_count(actions) == 3

    def test_offsite_conversion_counted(self):
        actions = [{
            "action_type": "offsite_conversion.fb_pixel_purchase",
            "value": 5,
        }]
        assert _purchase_count(actions) == 5

    def test_multiple_purchase_types_summed(self):
        """Meta's taxonomy has several purchase action types;
        all count."""
        actions = [
            {"action_type": "purchase", "value": 2},
            {"action_type": "omni_purchase", "value": 3},
        ]
        assert _purchase_count(actions) == 5

    def test_non_purchase_ignored(self):
        actions = [
            {"action_type": "add_to_cart", "value": 20},
            {"action_type": "lead", "value": 5},
        ]
        assert _purchase_count(actions) == 0

    def test_non_list_returns_zero(self):
        assert _purchase_count(None) == 0
        assert _purchase_count("garbage") == 0

    def test_garbage_value_skipped(self):
        actions = [
            {"action_type": "purchase", "value": "not-a-number"},
            {"action_type": "purchase", "value": 4},
        ]
        assert _purchase_count(actions) == 4


class TestAggregateSkus:
    def test_single_campaign_per_sku(self):
        campaigns = [{
            "campaign_name": "shopai:abc:galaxy",
            "spend": "50.00", "clicks": 200,
            "impressions": 5000,
            "actions": [{"action_type": "purchase", "value": 5}],
        }]
        recs, unmatched = _aggregate_to_skus(
            campaigns, avg_order_value_usd=30.0,
            days_active=7,
        )
        assert unmatched == 0
        assert len(recs) == 1
        r = recs[0]
        assert r.sku == "galaxy"
        assert r.orders == 5
        assert r.revenue_usd == 150.0
        assert r.ad_spend_usd == 50.0

    def test_two_campaigns_same_sku_sum(self):
        """Same handle across two launch attempts — sum them
        so the allocator sees the true aggregate."""
        campaigns = [
            {
                "campaign_name": "shopai:aaa:galaxy",
                "spend": "30", "clicks": 100,
                "actions": [
                    {"action_type": "purchase", "value": 3},
                ],
            },
            {
                "campaign_name": "shopai:bbb:galaxy",
                "spend": "20", "clicks": 50,
                "actions": [
                    {"action_type": "purchase", "value": 2},
                ],
            },
        ]
        recs, _ = _aggregate_to_skus(
            campaigns, avg_order_value_usd=25.0,
            days_active=7,
        )
        assert len(recs) == 1
        assert recs[0].orders == 5
        assert recs[0].ad_spend_usd == 50.0

    def test_unmatched_counted_not_included(self):
        campaigns = [
            {"campaign_name": "shopai:abc:galaxy", "spend": 10,
             "actions": []},
            {"campaign_name": "Manual Campaign", "spend": 5,
             "actions": []},
        ]
        recs, unmatched = _aggregate_to_skus(
            campaigns, avg_order_value_usd=20.0,
            days_active=7,
        )
        assert unmatched == 1
        assert len(recs) == 1
        assert recs[0].sku == "galaxy"

    def test_garbage_row_skipped(self):
        recs, unmatched = _aggregate_to_skus(
            ["not a dict", None,
             {"campaign_name": "shopai:a:b", "spend": 10,
              "actions": []}],
            avg_order_value_usd=20.0, days_active=7,
        )
        assert len(recs) == 1


class TestDaysFromPreset:
    def test_last_7d(self):
        assert _days_from_preset("last_7d") == 7

    def test_last_30d(self):
        assert _days_from_preset("last_30d") == 30

    def test_unknown_defaults_to_7(self):
        assert _days_from_preset("this_month") == 7

    def test_empty_defaults_to_7(self):
        assert _days_from_preset("") == 7


# ── run_budget_plan — skip paths ────────────────────────


@pytest.fixture
def tmp_reports(tmp_path):
    return str(tmp_path / "plans")


class TestSkipPaths:
    def test_no_budget_skips(self, monkeypatch, tmp_reports):
        monkeypatch.delenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", raising=False,
        )
        report = run_budget_plan(reports_dir=tmp_reports)
        assert report.skipped
        assert "BUDGET_USD" in report.error

    def test_router_exception_skips(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "100",
        )

        def boom():
            raise RuntimeError("adapter layer unavailable")

        with patch(
            "core.adapters.get_router", side_effect=boom,
        ):
            report = run_budget_plan(reports_dir=tmp_reports)
        assert report.skipped
        assert "router" in report.error

    def test_insights_not_ok_skips(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "100",
        )
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, error="no Meta creds",
        )
        report = run_budget_plan(
            router=fake_router, reports_dir=tmp_reports,
        )
        assert report.skipped
        assert "not ok" in report.error

    def test_empty_campaigns_skips(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "100",
        )
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"campaigns": []},
        )
        report = run_budget_plan(
            router=fake_router, reports_dir=tmp_reports,
        )
        assert report.skipped
        assert "no campaigns" in report.error

    def test_no_matching_names_skips(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "100",
        )
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"campaigns": [
                {"campaign_name": "Manual-2026-Q1",
                 "spend": 50, "actions": []},
            ]},
        )
        report = run_budget_plan(
            router=fake_router, reports_dir=tmp_reports,
        )
        assert report.skipped
        assert "matched" in report.error


# ── run_budget_plan — happy path ────────────────────────


class TestHappyPath:
    def test_writes_plan_and_returns_report(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "100",
        )
        monkeypatch.setenv(
            "SHOPAI_AVG_ORDER_VALUE_USD", "35",
        )
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"campaigns": [
                {"campaign_name": "shopai:abc:galaxy",
                 "spend": 80.0, "clicks": 200,
                 "impressions": 5000,
                 "actions": [{"action_type": "purchase",
                              "value": 20}]},
                {"campaign_name": "shopai:xyz:moon",
                 "spend": 40.0, "clicks": 80,
                 "impressions": 2000,
                 "actions": [{"action_type": "purchase",
                              "value": 4}]},
            ]},
        )
        report = run_budget_plan(
            router=fake_router, reports_dir=tmp_reports,
            seed=42,
        )
        assert not report.skipped
        assert report.campaigns_seen == 2
        assert report.skus_planned == 2
        assert report.total_daily_usd == 100.0
        assert report.plan_path
        # File written
        import os
        assert os.path.exists(report.plan_path)
        # Deterministic with seed
        import json
        with open(report.plan_path) as fh:
            saved = json.load(fh)
        assert saved["campaigns_seen"] == 2
        assert len(saved["allocations"]) == 2

    def test_env_overrides_propagate(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "200",
        )
        monkeypatch.setenv(
            "SHOPAI_BUDGET_MIN_PER_SKU", "20",
        )
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"campaigns": [
                {"campaign_name": "shopai:a:galaxy",
                 "spend": 100, "clicks": 300,
                 "actions": [{"action_type": "purchase",
                              "value": 30}]},
                {"campaign_name": "shopai:b:moon",
                 "spend": 60, "clicks": 80,
                 "actions": [{"action_type": "purchase",
                              "value": 2}]},
            ]},
        )
        report = run_budget_plan(
            router=fake_router, reports_dir=tmp_reports,
            seed=1,
        )
        # Both SKUs should receive ≥ min floor
        for a in report.allocations:
            assert a.recommended_daily_usd >= 20.0 - 0.01

    def test_unmatched_count_preserved(
        self, monkeypatch, tmp_reports,
    ):
        monkeypatch.setenv(
            "SHOPAI_TOTAL_DAILY_BUDGET_USD", "100",
        )
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"campaigns": [
                {"campaign_name": "shopai:a:galaxy",
                 "spend": 50, "actions": []},
                {"campaign_name": "Manual-Boost",
                 "spend": 30, "actions": []},
                {"campaign_name": "Another Manual",
                 "spend": 10, "actions": []},
            ]},
        )
        report = run_budget_plan(
            router=fake_router, reports_dir=tmp_reports,
            seed=1,
        )
        assert report.campaigns_seen == 3
        assert report.skus_planned == 1
        # Plan JSON includes the unmatched count
        import json
        with open(report.plan_path) as fh:
            saved = json.load(fh)
        assert saved["campaigns_unmatched"] == 2


# ── list_plans ──────────────────────────────────────────


class TestListPlans:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert list_plans(str(tmp_path / "nope")) == []

    def test_newest_first(self, tmp_path):
        import json, os
        os.makedirs(tmp_path, exist_ok=True)
        for i, plan_id in enumerate([
            "2026-04-20-100000",
            "2026-04-21-100000",
            "2026-04-22-100000",
        ]):
            path = tmp_path / f"{plan_id}.json"
            path.write_text(json.dumps({
                "plan_id": plan_id,
                "total_daily_usd": 100, "allocations": [],
            }))
        plans = list_plans(str(tmp_path), limit=5)
        ids = [p["plan_id"] for p in plans]
        assert ids == [
            "2026-04-22-100000",
            "2026-04-21-100000",
            "2026-04-20-100000",
        ]

    def test_limit_respected(self, tmp_path):
        import json
        for i in range(10):
            (tmp_path / f"2026-04-{i:02d}-000000.json"
             ).write_text(json.dumps({
                "plan_id": f"2026-04-{i:02d}-000000",
                "allocations": [],
            }))
        plans = list_plans(str(tmp_path), limit=3)
        assert len(plans) == 3

    def test_corrupt_json_skipped(self, tmp_path):
        import json
        (tmp_path / "good.json").write_text(
            json.dumps({"plan_id": "good"}),
        )
        (tmp_path / "bad.json").write_text(
            "not json at all",
        )
        plans = list_plans(str(tmp_path))
        ids = {p.get("plan_id") for p in plans}
        assert "good" in ids
        # "bad" silently dropped


# ── Autopilot CycleSummary wire ─────────────────────────


class TestAutopilotWire:
    def test_cycle_summary_carries_count(self):
        from scripts import autopilot_loop as al
        s = al.CycleSummary(
            cycle=1, ts=0, mode="live",
            launches=0, successful=0,
            distilled_proposals=0, accepted=0,
            duration_s=0.0,
            budget_plan_skus=12,
        )
        assert s.as_dict()["budget_plan_skus"] == 12

    def test_loop_config_budget_plan_every(self):
        from scripts import autopilot_loop as al
        cfg = al.LoopConfig(
            seeds_path="/tmp/seeds.json",
            max_iterations=1,
            interval_s=0.01,
            log_path="/tmp/loop.log",
            budget_plan_every=4,
        )
        assert cfg.budget_plan_every == 4

    def test_loop_config_default_budget_plan_every(self):
        from scripts import autopilot_loop as al
        cfg = al.LoopConfig(
            seeds_path="/tmp/seeds.json",
            max_iterations=1,
            interval_s=0.01,
            log_path="/tmp/loop.log",
        )
        assert cfg.budget_plan_every == 4
