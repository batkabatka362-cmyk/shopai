"""W963-119: per-store budget cap tracking tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engines.per_store_costs import recorder as cost_recorder
from engines.per_store_quota import (
    PerStoreQuotaEngine,
    QuotaSnapshot,
    QuotaState,
    compute_all_snapshots,
    compute_snapshot,
    critical_stores,
    resolve_cap,
    resolve_warn_ratio,
    warn_stores,
)
from engines.per_store_quota.budget_config import (
    _normalise_adapter_for_env,
    _normalise_sid_for_env,
    _parse_amount,
)


@pytest.fixture(autouse=True)
def _isolated_costs_log(tmp_path, monkeypatch):
    """Each test gets its own cost log so we can control
    the 'spend' input precisely. Also patches the query
    module's path so the quota tracker reads from the same
    file."""
    live = tmp_path / "per_store_costs.jsonl"
    archive = tmp_path / "per_store_costs.archive.jsonl"
    monkeypatch.setattr(cost_recorder, "DATA_PATH", live)
    monkeypatch.setattr(cost_recorder, "ARCHIVE_PATH", archive)
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    yield live


def _seed_events(live: Path, events: list[dict]) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    with open(live, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


# ── budget_config helpers ─────────────────────────────────


class TestBudgetConfigHelpers:
    def test_normalise_sid(self):
        assert _normalise_sid_for_env("store-a") == "STORE_A"
        assert _normalise_sid_for_env("Store_B") == "STORE_B"
        assert _normalise_sid_for_env("") == ""

    def test_normalise_adapter(self):
        assert _normalise_adapter_for_env(
            "meta_ads",
        ) == "META_ADS"
        assert _normalise_adapter_for_env(
            "cj-dropshipping",
        ) == "CJ_DROPSHIPPING"

    def test_parse_amount_accepts_plain_number(self):
        assert _parse_amount("5") == 5.0
        assert _parse_amount("5.50") == 5.5

    def test_parse_amount_strips_currency(self):
        assert _parse_amount("$5.00") == 5.0
        assert _parse_amount("10 USD") == 10.0

    def test_parse_amount_unlimited_words(self):
        for w in ("unlimited", "none", "off", "0"):
            assert _parse_amount(w) == 0.0

    def test_parse_amount_invalid_returns_none(self):
        """W963-124 round-8 #4: typos like 'garbage' or
        '1,000' (pre-fix returned 0.0 = silently uncapped
        the wallet) now return None so the resolver
        falls through to the next level instead of
        treating a typo as 'unlimited'."""
        assert _parse_amount("garbage") is None
        assert _parse_amount("") is None
        assert _parse_amount(None) is None

    def test_parse_amount_thousands_separator(self):
        """W963-124: '1,000' now parses correctly (was
        treated as 0/unlimited pre-fix)."""
        assert _parse_amount("1,000") == 1000.0
        assert _parse_amount("5_000") == 5000.0
        assert _parse_amount("$1,500.50") == 1500.50

    def test_parse_amount_unlimited_distinct_from_unset(
        self,
    ):
        """W963-124: 'unlimited' / 'none' / 'off' return
        0.0 (explicit unlimited). 'unset' / '' / None
        return None (no value)."""
        assert _parse_amount("unlimited") == 0.0
        assert _parse_amount("none") == 0.0
        assert _parse_amount("off") == 0.0
        assert _parse_amount("unset") is None
        assert _parse_amount("null") is None


class TestResolveCap:
    def test_no_env_set_returns_zero(self, monkeypatch):
        for v in (
            "SHOPAI_DAILY_BUDGET_USD",
            "OPENAI_DAILY_BUDGET_USD",
            "SHOPAI_STORE_STORE_A_DAILY_BUDGET_USD",
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
        ):
            monkeypatch.delenv(v, raising=False)
        assert resolve_cap(
            store_id="store_a", adapter="openai",
        ) == 0.0

    def test_fleet_total_cap(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_DAILY_BUDGET_USD", "100",
        )
        assert resolve_cap() == 100.0

    def test_per_store_overrides_fleet(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_DAILY_BUDGET_USD", "100",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_DAILY_BUDGET_USD", "25",
        )
        assert resolve_cap(store_id="store_a") == 25.0
        # Other stores still get fleet
        assert resolve_cap(store_id="store_b") == 100.0

    def test_per_adapter_overrides_fleet(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_DAILY_BUDGET_USD", "100",
        )
        monkeypatch.setenv(
            "OPENAI_DAILY_BUDGET_USD", "5",
        )
        assert resolve_cap(
            adapter="openai",
        ) == 5.0
        # Without adapter arg -> fleet total
        assert resolve_cap() == 100.0

    def test_per_store_per_adapter_wins(self, monkeypatch):
        """Most specific cap wins over all other levels."""
        monkeypatch.setenv(
            "SHOPAI_DAILY_BUDGET_USD", "100",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_DAILY_BUDGET_USD", "25",
        )
        monkeypatch.setenv(
            "OPENAI_DAILY_BUDGET_USD", "10",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "3",
        )
        # store_a + openai: most specific wins
        assert resolve_cap(
            store_id="store_a", adapter="openai",
        ) == 3.0

    def test_hyphen_in_sid_normalises(self, monkeypatch):
        """Operator may name stores with hyphens. Env var
        uses underscores."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_DAILY_BUDGET_USD", "10",
        )
        assert resolve_cap(store_id="store-a") == 10.0


class TestResolveWarnRatio:
    def test_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_BUDGET_WARN_RATIO", raising=False,
        )
        assert resolve_warn_ratio() == 0.7

    def test_custom(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_BUDGET_WARN_RATIO", "0.5",
        )
        assert resolve_warn_ratio() == 0.5

    def test_clamps_high(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_BUDGET_WARN_RATIO", "2.0",
        )
        assert resolve_warn_ratio() == 0.99

    def test_clamps_low(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_BUDGET_WARN_RATIO", "0.0",
        )
        assert resolve_warn_ratio() == 0.1

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_BUDGET_WARN_RATIO", "garbage",
        )
        assert resolve_warn_ratio() == 0.7


# ── compute_snapshot ──────────────────────────────────────


class TestComputeSnapshot:
    def test_unlimited_when_no_cap(
        self, _isolated_costs_log, monkeypatch,
    ):
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 5.00, "latency_ms": 100,
            "ok": True,
        }])
        snap = compute_snapshot(
            "store_a", adapter="openai",
        )
        assert snap.state == QuotaState.UNLIMITED
        assert snap.cap_usd == 0.0

    def test_ok_when_well_under_cap(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 0.50, "latency_ms": 100,
            "ok": True,
        }])
        snap = compute_snapshot(
            "store_a", adapter="openai",
        )
        assert snap.state == QuotaState.OK
        assert snap.cap_usd == 10.0
        assert snap.spend_usd == 0.50

    def test_warn_at_warn_ratio(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        # 7.5 / 10 = 75% -> WARN (default warn_ratio=0.7)
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 7.50, "latency_ms": 100,
            "ok": True,
        }])
        snap = compute_snapshot(
            "store_a", adapter="openai",
        )
        assert snap.state == QuotaState.WARN

    def test_critical_at_cap(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.50, "latency_ms": 100,
            "ok": True,
        }])
        snap = compute_snapshot(
            "store_a", adapter="openai",
        )
        assert snap.state == QuotaState.CRITICAL
        assert snap.headroom_usd == 0.0
        assert snap.pct_used > 100.0

    def test_total_aggregates_all_adapters(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_DAILY_BUDGET_USD", "5",
        )
        now = time.time()
        _seed_events(_isolated_costs_log, [
            {
                "ts": now, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 2.0, "ok": True,
            },
            {
                "ts": now, "store_id": "store_a",
                "adapter": "anthropic", "capability": "chat",
                "cost_usd": 2.5, "ok": True,
            },
        ])
        # adapter="" -> total spend
        snap = compute_snapshot("store_a", adapter="")
        assert snap.spend_usd == pytest.approx(4.5)
        assert snap.cap_usd == 5.0
        # 4.5/5 = 90% -> CRITICAL (90% > 100%? No, 90 < 100)
        # default warn_ratio 0.7, so 90% > 70% -> WARN
        assert snap.state == QuotaState.WARN


# ── critical / warn helpers ───────────────────────────────


class TestAlertHelpers:
    def test_critical_stores_only_critical(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        now = time.time()
        _seed_events(_isolated_costs_log, [
            {
                "ts": now, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 11.0, "ok": True,  # exceeded
            },
            {
                "ts": now, "store_id": "store_b",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 5.0, "ok": True,  # ok
            },
        ])
        crit = critical_stores()
        # store_a should be CRITICAL
        assert any(
            s.store_id == "store_a"
            and s.adapter == "openai"
            for s in crit
        )
        # store_b should NOT be CRITICAL
        assert not any(
            s.store_id == "store_b" for s in crit
        )

    def test_warn_stores_only_warn(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 8.0, "ok": True,  # 80% = WARN
        }])
        warn = warn_stores()
        assert any(
            s.store_id == "store_a"
            and s.adapter == "openai"
            for s in warn
        )


# ── compute_all_snapshots ─────────────────────────────────


class TestComputeAllSnapshots:
    def test_includes_total_per_store(
        self, _isolated_costs_log,
    ):
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 0.01, "ok": True,
        }])
        snaps = compute_all_snapshots()
        # One total + one per-adapter row
        assert any(
            s.adapter == "" and s.store_id == "store_a"
            for s in snaps
        )
        assert any(
            s.adapter == "openai" and s.store_id == "store_a"
            for s in snaps
        )

    def test_critical_sorts_first(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        now = time.time()
        _seed_events(_isolated_costs_log, [
            {
                "ts": now, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.5, "ok": True,
            },
            {
                "ts": now, "store_id": "store_b",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 11.0, "ok": True,  # critical
            },
        ])
        snaps = compute_all_snapshots()
        # First snapshot should be CRITICAL
        assert snaps[0].state == QuotaState.CRITICAL
        assert snaps[0].store_id == "store_b"


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self, _isolated_costs_log):
        r = PerStoreQuotaEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self, _isolated_costs_log):
        r = PerStoreQuotaEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self, _isolated_costs_log):
        r = PerStoreQuotaEngine().run("nope")
        assert r["status"] == "error"

    def test_carries_engine_name(self, _isolated_costs_log):
        r = PerStoreQuotaEngine().run({})
        assert r["meta"]["engine"] == "per_store_quota"

    def test_critical_view(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 15.0, "ok": True,
        }])
        r = PerStoreQuotaEngine().run({
            "data": {"view": "critical"},
        })
        assert r["data"]["view"] == "critical"
        # At least one critical (could be store_a/openai
        # AND store_a/total since the per-store total is
        # also 15 > 0)
        snaps = r["data"]["snapshots"]
        assert any(
            s["store_id"] == "store_a"
            and s["state"] == "critical"
            for s in snaps
        )

    def test_single_view(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed_events(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 1.5, "ok": True,
        }])
        r = PerStoreQuotaEngine().run({
            "data": {
                "view": "single",
                "store_id": "store_a",
                "adapter": "openai",
            },
        })
        snap = r["data"]["snapshot"]
        assert snap["state"] == "ok"
        assert snap["cap_usd"] == 10.0
        assert snap["spend_usd"] == 1.5
