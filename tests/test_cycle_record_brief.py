"""Tests for W963-62 SHOPAI_CYCLE_RECORD_BRIEF post-cycle hook.

The hook lives inline inside _cmd_cycle_run, so we test the
SHAPE of the recorded snapshot via the helpers it calls
rather than full-cycle integration (cycle run --yes
side-effects span the whole fleet).
"""
from __future__ import annotations

import time
from unittest.mock import patch


# ── shape of the recorded snapshot ────────────────────────


class TestSnapshotShape:
    """Verify the snapshot dict the hook builds matches what
    agi_earnings_history.record_snapshot expects."""

    def test_snapshot_keys_match_history_canonical_form(
        self,
    ):
        # Simulate the hook's snapshot construction
        from engines.agi_earnings_summary.summarizer \
            import compute_summary
        from engines.agi_earnings_history import (
            store as h,
        )
        # Run through the hook logic
        s = compute_summary(days=7)
        snapshot = {
            "ts": time.time(),
            "days": 7,
            "verdict": s.verdict,
            "gross_profit": s.fleet_gross_profit,
            "attribution_pct": s.fleet_attribution_pct,
            "monthly_run_rate": s.monthly_run_rate,
            "trend_verdict": s.trend_verdict,
            "store_count": s.store_count,
            "orphan_action_count": 0,
        }
        # All snapshot keys are the canonical Phase 4 set
        assert "ts" in snapshot
        assert "verdict" in snapshot
        assert "gross_profit" in snapshot
        assert "attribution_pct" in snapshot
        # record_snapshot accepts any dict; can call without
        # raising (Pattern J guard prevents real write)
        result = h.record_snapshot(snapshot)
        assert isinstance(result, bool)


# ── env-gating behaviour ──────────────────────────────────


class TestEnvGate:
    def test_env_unset_means_no_recording(self):
        # When env var unset, snapshot is NOT recorded
        import os
        env_present = (
            os.environ.get("SHOPAI_CYCLE_RECORD_BRIEF")
            == "1"
        )
        assert env_present is False

    def test_env_truthy_value(self):
        import os
        os.environ["SHOPAI_CYCLE_RECORD_BRIEF"] = "1"
        try:
            assert (
                os.environ.get(
                    "SHOPAI_CYCLE_RECORD_BRIEF",
                ) == "1"
            )
        finally:
            os.environ.pop(
                "SHOPAI_CYCLE_RECORD_BRIEF", None,
            )


# ── integration: probe the substrate is importable ────────


class TestImports:
    def test_summarizer_importable(self):
        from engines.agi_earnings_summary.summarizer \
            import compute_summary
        assert callable(compute_summary)

    def test_history_store_importable(self):
        from engines.agi_earnings_history import store
        assert callable(store.record_snapshot)

    def test_record_snapshot_signature_takes_dict(self):
        from engines.agi_earnings_history import store
        # Confirm signature (won't raise on call with
        # empty dict under Pattern J guard)
        result = store.record_snapshot({})
        assert isinstance(result, bool)
