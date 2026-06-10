"""W963-120: per-store quota autopause bridge tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engines.per_store_costs import recorder as cost_recorder
from engines.per_store_quota import maybe_autopause
from engines.per_store_quota.autopause import (
    _DEFAULT_SPEND_DOMAINS,
    _is_autopause_enabled,
    _resolve_spend_domains,
)


@pytest.fixture(autouse=True)
def _isolated_costs_log(tmp_path, monkeypatch):
    live = tmp_path / "per_store_costs.jsonl"
    archive = tmp_path / "per_store_costs.archive.jsonl"
    monkeypatch.setattr(cost_recorder, "DATA_PATH", live)
    monkeypatch.setattr(
        cost_recorder, "ARCHIVE_PATH", archive,
    )
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    yield live


def _seed(live: Path, events: list[dict]) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    with open(live, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


# ── Configuration ─────────────────────────────────────────


class TestEnvHelpers:
    def test_default_spend_domains(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_QUOTA_AUTOPAUSE_DOMAINS",
            raising=False,
        )
        assert _resolve_spend_domains() == (
            _DEFAULT_SPEND_DOMAINS
        )

    def test_custom_spend_domains(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE_DOMAINS",
            "marketing,fulfillment",
        )
        assert _resolve_spend_domains() == (
            "marketing", "fulfillment",
        )

    def test_empty_custom_falls_back_to_default(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE_DOMAINS", "",
        )
        assert _resolve_spend_domains() == (
            _DEFAULT_SPEND_DOMAINS
        )

    def test_autopause_disabled_by_default(
        self, monkeypatch,
    ):
        monkeypatch.delenv(
            "SHOPAI_QUOTA_AUTOPAUSE", raising=False,
        )
        assert _is_autopause_enabled() is False

    def test_autopause_enabled_with_one(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        assert _is_autopause_enabled() is True

    def test_autopause_enabled_with_true(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "true",
        )
        assert _is_autopause_enabled() is True


# ── maybe_autopause ───────────────────────────────────────


class TestMaybeAutopause:
    def test_no_critical_stores_returns_empty_report(
        self, _isolated_costs_log,
    ):
        report = maybe_autopause()
        assert report.critical_store_count == 0
        assert report.actions == []

    def test_dry_run_when_disabled(
        self, _isolated_costs_log, monkeypatch,
    ):
        """SHOPAI_QUOTA_AUTOPAUSE unset -> bridge reports
        would-pause decisions but does NOT call disarm.
        """
        monkeypatch.delenv(
            "SHOPAI_QUOTA_AUTOPAUSE", raising=False,
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.0, "ok": True,
        }])

        with patch(
            "core.automation.autonomy_armed.disarm",
        ) as mock_disarm:
            report = maybe_autopause()

        # store_a is critical -> would pause its
        # spend-class domains
        assert report.critical_store_count == 1
        assert report.would_apply_count > 0
        # But disarm() was NEVER called (dry-run)
        mock_disarm.assert_not_called()
        # And no actions report applied=True
        assert all(
            not a.applied for a in report.actions
        )

    def test_live_disarm_when_enabled(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 12.0, "ok": True,
        }])

        with patch(
            "core.automation.autonomy_armed.disarm",
            return_value=True,
        ) as mock_disarm:
            report = maybe_autopause()

        assert report.applied_count == len(
            _DEFAULT_SPEND_DOMAINS
        )
        # disarm called once per spend-class domain for
        # store_a
        assert mock_disarm.call_count == len(
            _DEFAULT_SPEND_DOMAINS
        )
        # Each disarm call scoped to store_a (not fleet)
        for call_args in mock_disarm.call_args_list:
            kwargs = call_args.kwargs
            assert kwargs.get("store_id") == "store_a"

    def test_per_store_scope_only_pauses_affected_store(
        self, _isolated_costs_log, monkeypatch,
    ):
        """A critical store_a does NOT pause store_b's
        domains. The whole point of per-store autopause."""
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [
            {
                "ts": time.time(), "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 100.0, "ok": True,
            },
            {
                "ts": time.time(), "store_id": "store_b",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.50, "ok": True,
            },
        ])

        with patch(
            "core.automation.autonomy_armed.disarm",
            return_value=True,
        ) as mock_disarm:
            report = maybe_autopause()

        # store_a paused; store_b untouched
        store_ids_paused = {
            call.kwargs.get("store_id")
            for call in mock_disarm.call_args_list
        }
        assert "store_a" in store_ids_paused
        assert "store_b" not in store_ids_paused

    def test_fleet_pseudo_store_skipped(
        self, _isolated_costs_log, monkeypatch,
    ):
        """The synthetic '(fleet)' key from events without
        active_store should NOT trigger autopause -- there
        is no fleet-wide autopause concept here (W47
        handles that)."""
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_DAILY_BUDGET_USD", "5",
        )
        # Event without a store_id -> aggregates under
        # "(fleet)"
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 100.0, "ok": True,
        }])

        with patch(
            "core.automation.autonomy_armed.disarm",
        ) as mock_disarm:
            report = maybe_autopause()

        # No store-scoped disarm called (the fleet pseudo-
        # store is excluded)
        assert mock_disarm.call_count == 0

    def test_custom_domain_list_overrides_default(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE_DOMAINS",
            "marketing,fulfillment",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.0, "ok": True,
        }])

        with patch(
            "core.automation.autonomy_armed.disarm",
            return_value=True,
        ) as mock_disarm:
            report = maybe_autopause()

        domains_paused = {
            call.args[0] if call.args
            else call.kwargs.get("domain")
            for call in mock_disarm.call_args_list
        }
        assert "marketing" in domains_paused
        assert "fulfillment" in domains_paused
        # NOT in default list anymore
        assert "customer_outreach" not in domains_paused

    def test_disarm_exception_captured_in_action(
        self, _isolated_costs_log, monkeypatch,
    ):
        """When disarm() raises for one domain, the
        bridge captures the error per-action + continues
        with the remaining domains."""
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.0, "ok": True,
        }])

        def selective_raise(
            domain, store_id="", *args, **kwargs,
        ):
            if domain == "marketing":
                raise RuntimeError("test: simulated")
            return True

        with patch(
            "core.automation.autonomy_armed.disarm",
            side_effect=selective_raise,
        ):
            report = maybe_autopause()

        # The marketing action has an error
        marketing_actions = [
            a for a in report.actions
            if a.domain == "marketing"
        ]
        assert len(marketing_actions) == 1
        assert "simulated" in marketing_actions[0].error
        # Other domains still attempted + applied
        applied = [a for a in report.actions if a.applied]
        assert len(applied) > 0

    def test_report_carries_window_hours(
        self, _isolated_costs_log,
    ):
        report = maybe_autopause(window_hours=12.0)
        assert report.window_hours == 12.0

    def test_idempotent_at_module_level(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Calling maybe_autopause twice in a row should
        not raise + produces the same shape report (state
        is held by autonomy_armed -- here we just verify
        no crash + we tolerate empty disarm returns)."""
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.0, "ok": True,
        }])
        with patch(
            "core.automation.autonomy_armed.disarm",
            return_value=True,
        ):
            report1 = maybe_autopause()
        with patch(
            "core.automation.autonomy_armed.disarm",
            return_value=False,  # already disarmed
        ):
            report2 = maybe_autopause()
        assert report1.critical_store_count == (
            report2.critical_store_count
        )
        # report2.applied_count = 0 because disarm
        # returned False (idempotent: already disarmed)
        assert report2.applied_count == 0
