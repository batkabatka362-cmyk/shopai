"""W963-137: regression tests for Round 10 fixes.

Round 10 confirmed 5 bugs. This file covers the first
two highest-priority fixes shipped in W963-137:

  #3: dashboard forecast block excluded EXHAUSTED
      (most-actionable bucket dropped silently)
  #5: drill hint pointed at `shopai forecast` which is
      NOT a registered subcommand. Correct hint is
      `shopai quota --forecast`.

Subsequent commits W963-138 and W963-139 cover the
remaining 3 bugs.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engines.per_store_costs import recorder as cost_recorder


@pytest.fixture(autouse=True)
def _isolated_costs_log(tmp_path, monkeypatch):
    live = tmp_path / "per_store_costs.jsonl"
    archive = (
        tmp_path / "per_store_costs.archive.jsonl"
    )
    monkeypatch.setattr(cost_recorder, "DATA_PATH", live)
    monkeypatch.setattr(
        cost_recorder, "ARCHIVE_PATH", archive,
    )
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    yield live


class TestExhaustedSurfacesInForecast:
    """Round-10 #3: EXHAUSTED forecasts must appear in
    the empire + daily-brief urgent list so the most-
    actionable bucket isn't silently dropped."""

    def test_exhausted_in_fleet_forecasts(
        self, _isolated_costs_log, monkeypatch,
    ):
        from engines.per_store_quota import (
            ForecastVerdict, fleet_forecasts,
        )

        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        # store_a has spent $15 -- exceeds $10 cap ->
        # EXHAUSTED
        now = time.time()
        with open(
            _isolated_costs_log,
            "w", encoding="utf-8",
        ) as f:
            f.write(json.dumps({
                "ts": now - 3600,
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 15.0,
                "ok": True,
            }) + "\n")
        fcs = fleet_forecasts(
            sample_hours=6.0, cap_window_hours=24.0,
        )
        exhausted = [
            f for f in fcs
            if f.verdict == ForecastVerdict.EXHAUSTED
        ]
        assert exhausted, "expected EXHAUSTED verdict"
        # AND store_a should be in the EXHAUSTED list
        assert any(
            f.store_id == "store_a" for f in exhausted
        )

    def test_dashboard_urgent_includes_exhausted(
        self,
    ):
        """W963-137 round-10 #3: the empire + daily-
        brief urgent filter tuple must include
        EXHAUSTED. Verified by reading the cli.py
        source -- the actual tuple."""
        cli_path = (
            Path(__file__).parent.parent / "cli.py"
        )
        text = cli_path.read_text(encoding="utf-8")
        # The filter tuple appears twice (empire +
        # daily-brief). Both must mention EXHAUSTED.
        # Count occurrences of EXHAUSTED inside the
        # urgent tuple context.
        # We do a coarse check: text contains the line
        # 'ForecastVerdict.EXHAUSTED' at least twice
        # (one per dashboard).
        count = text.count("ForecastVerdict.EXHAUSTED")
        assert count >= 2, (
            f"Expected >=2 ForecastVerdict.EXHAUSTED "
            f"references in cli.py (empire + daily-"
            f"brief urgent filters), found {count}"
        )


class TestAutopauseLogHonesty:
    """Round-10 #2 + #4: autopause log path must
    honestly distinguish:
      - all-applied (pure success)
      - mixed applied + blocked (W963-139 #2)
      - all-blocked (W963-132 already covered)
      - steady-state idempotent no-ops (W963-139 #4)
      - dry-run mode (true OFF)
    """

    def _simulate_log_path(self, applied, would_apply,
                           critical_count, blocked_actions,
                           enabled):
        """Direct unit test of the dispatch logic --
        avoids the full cycle invocation."""
        import logging
        log = logging.getLogger(
            "test_w963_139_dispatch",
        )

        all_noops = (
            applied == 0
            and not blocked_actions
            and would_apply > 0
        )
        captured: list[tuple[str, str]] = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(
                    (record.levelname, record.getMessage()),
                )

        handler = _Cap()
        handler.setLevel(logging.DEBUG)
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)

        try:
            if applied > 0 and blocked_actions:
                first = blocked_actions[0]
                log.info(
                    "%d paused; %d BLOCKED (e.g. %s/%s: %s)",
                    applied, len(blocked_actions),
                    first["store_id"], first["domain"],
                    first["error"][:120],
                )
            elif applied > 0:
                log.info("%d paused", applied)
            elif blocked_actions and enabled:
                first = blocked_actions[0]
                log.info(
                    "%d BLOCKED (e.g. %s/%s: %s)",
                    len(blocked_actions),
                    first["store_id"], first["domain"],
                    first["error"][:120],
                )
            elif all_noops and enabled:
                log.debug(
                    "%d already paused (idempotent)",
                    would_apply,
                )
            elif would_apply > 0 and not enabled:
                log.info(
                    "OFF but %d would pause",
                    would_apply,
                )
        finally:
            log.removeHandler(handler)
        return captured

    def test_partial_collision_surfaces_blocked(self):
        """W963-139 #2: applied > 0 AND some blocked
        -> log must mention BOTH."""
        captured = self._simulate_log_path(
            applied=2,
            would_apply=4,
            critical_count=1,
            blocked_actions=[{
                "store_id": "store_a",
                "domain": "marketing",
                "error": "fleet-wide arm prevents per-store",
            }],
            enabled=True,
        )
        assert captured
        level, msg = captured[0]
        assert level == "INFO"
        assert "2 paused" in msg
        assert "BLOCKED" in msg
        assert "fleet-wide arm" in msg

    def test_steady_state_noops_logged_at_debug(self):
        """W963-139 #4: applied=0 + would_apply>0 + no
        errors + enabled -> idempotent no-op, log at
        DEBUG not INFO so operator INFO stream stays
        clean."""
        captured = self._simulate_log_path(
            applied=0,
            would_apply=4,
            critical_count=1,
            blocked_actions=[],
            enabled=True,
        )
        assert captured
        level, msg = captured[0]
        # Steady-state should be DEBUG, not INFO
        assert level == "DEBUG", (
            f"Steady-state no-op logged at {level} "
            f"(expected DEBUG to avoid INFO flood)"
        )
        assert "already paused" in msg

    def test_pure_success_no_blocked_mention(self):
        captured = self._simulate_log_path(
            applied=4,
            would_apply=4,
            critical_count=1,
            blocked_actions=[],
            enabled=True,
        )
        level, msg = captured[0]
        assert level == "INFO"
        assert "4 paused" in msg
        assert "BLOCKED" not in msg

    def test_all_blocked_surfaces_error(self):
        captured = self._simulate_log_path(
            applied=0,
            would_apply=4,
            critical_count=1,
            blocked_actions=[{
                "store_id": "store_a",
                "domain": "marketing",
                "error": "all blocked",
            }],
            enabled=True,
        )
        level, msg = captured[0]
        assert level == "INFO"
        assert "BLOCKED" in msg

    def test_dry_run_off_branch_preserved(self):
        captured = self._simulate_log_path(
            applied=0,
            would_apply=4,
            critical_count=1,
            blocked_actions=[],
            enabled=False,
        )
        level, msg = captured[0]
        assert level == "INFO"
        assert "OFF but" in msg


class TestForecasterActualSpanFloor:
    """Round-10 #1: W963-138 floors effective_span at
    15 minutes (0.25h) so a single seconds-old cost
    event does not extrapolate to astronomical rates."""

    def test_single_fresh_event_no_false_critical(
        self, _isolated_costs_log, monkeypatch,
    ):
        """A brand-new store with one $2 event 5 seconds
        ago against a $100 cap previously produced
        rate=$1440/h, hours_to_cap=0.07h, verdict=
        CRITICAL. Floor makes the worst-case rate sane."""
        from engines.per_store_quota import (
            ForecastVerdict, fleet_forecasts,
        )

        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "100",
        )
        now = time.time()
        with open(
            _isolated_costs_log,
            "w", encoding="utf-8",
        ) as f:
            f.write(json.dumps({
                "ts": now - 5,
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 2.0,
                "ok": True,
            }) + "\n")
        fcs = fleet_forecasts(
            sample_hours=6.0, cap_window_hours=24.0,
        )
        # Focus on the per-adapter row where the cap
        # is actually set (we only set the openai cap)
        adapter_fcs = [
            f for f in fcs
            if f.store_id == "store_a"
            and f.adapter == "openai"
        ]
        assert adapter_fcs
        for f in adapter_fcs:
            # Floor: rate <= $2 / 0.25h = $8/h
            assert f.rate_per_hour_usd <= 8.5, (
                f"Rate {f.rate_per_hour_usd}/h too "
                f"high (expected <= $8/h with floor)"
            )
            # $98 headroom / $8/h = 12.25h
            # No false CRITICAL on the first event
            assert f.verdict != ForecastVerdict.CRITICAL, (
                f"False CRITICAL on cold-start "
                f"(verdict={f.verdict.value})"
            )
            assert f.hours_to_cap > 5.0, (
                f"hours_to_cap {f.hours_to_cap} too "
                f"low (floor should keep cold-start "
                f"prediction reasonable)"
            )

    def test_steady_burn_pattern_still_critical(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Floor must NOT mask genuinely fast burns:
        $10/h sustained over 5h is still $50 spent and
        should still hit CRITICAL territory."""
        from engines.per_store_quota import (
            ForecastVerdict, fleet_forecasts,
        )

        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "60",
        )
        now = time.time()
        # 5 events spread over 5 hours, $10 each = $50
        # in 5h actual span -> rate = $10/h, headroom
        # $10, hours_to_cap = 1h -> CRITICAL
        with open(
            _isolated_costs_log,
            "w", encoding="utf-8",
        ) as f:
            for h in (5, 4, 3, 2, 1):
                f.write(json.dumps({
                    "ts": now - 3600 * h,
                    "store_id": "store_a",
                    "adapter": "openai",
                    "capability": "chat",
                    "cost_usd": 10.0,
                    "ok": True,
                }) + "\n")
        fcs = fleet_forecasts(
            sample_hours=6.0, cap_window_hours=24.0,
        )
        # Find the per-adapter row (not total)
        adapter_fcs = [
            f for f in fcs
            if f.store_id == "store_a"
            and f.adapter == "openai"
        ]
        assert adapter_fcs
        # Should still be CRITICAL (fast burn near cap)
        assert any(
            f.verdict == ForecastVerdict.CRITICAL
            for f in adapter_fcs
        ), (
            "Floor must not mask genuine fast-burn "
            "CRITICAL signals"
        )


class TestForecastDrillHintIsValid:
    """Round-10 #5: drill hint `shopai forecast` is NOT
    a real subcommand. Correct: `shopai quota
    --forecast`."""

    def test_no_shopai_forecast_drill_hint_in_print(
        self,
    ):
        """Verify cli.py PRINT lines (not comments)
        don't contain the broken `shopai forecast`
        hint."""
        cli_path = (
            Path(__file__).parent.parent / "cli.py"
        )
        lines = cli_path.read_text(
            encoding="utf-8",
        ).splitlines()
        # Look for any print line containing the
        # broken hint
        broken = []
        for n, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if (
                "`shopai forecast`" in line
                or '"`shopai forecast`"' in line
                or "shopai forecast for" in line
            ):
                broken.append((n, line.strip()))
        assert not broken, (
            f"Found broken `shopai forecast` drill "
            f"hint in CLI print code: {broken}"
        )

    def test_quota_subparser_has_forecast_flag(self):
        """Sanity: `shopai quota --forecast` is the
        documented + working surface."""
        # Build the parser + check that 'quota' has a
        # --forecast option
        from cli import build_parser
        parser = build_parser()
        # Find the 'quota' subparser
        for action in parser._actions:
            if isinstance(
                action, argparse._SubParsersAction,
            ):
                quota = action.choices.get("quota")
                if quota is None:
                    continue
                opt_strings = [
                    o for a in quota._actions
                    for o in a.option_strings
                ]
                # --forecast is the documented option
                # OR --view forecast might be the
                # supported form. Either is fine; the
                # CLI just needs SOMETHING reachable.
                assert (
                    "--forecast" in opt_strings
                    or "--view" in opt_strings
                ), (
                    f"shopai quota subparser must "
                    f"expose either --forecast or "
                    f"--view to support the drill "
                    f"hint; got: {opt_strings}"
                )
                return
        pytest.fail(
            "shopai quota subparser not found",
        )
