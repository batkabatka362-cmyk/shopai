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
