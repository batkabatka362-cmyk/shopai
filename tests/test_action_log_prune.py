"""W963-182: action_log prune_events_matching tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from core.automation.action_log import (
    load_log,
    log_size,
    prune_events_matching,
    prune_events_older_than,
    save_log,
)


def _seed_log(
    path: Path,
    events: list[dict],
) -> None:
    """Write events directly, bypassing the test-env guard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events), encoding="utf-8")


class TestPruneMatching:
    def test_empty_log_returns_zero(self, tmp_path):
        # Patch is_test_environment so prune actually runs
        with patch(
            "core.automation.action_log."
            "is_test_environment",
            return_value=False,
        ):
            removed = prune_events_matching(
                tmp_path / "nope.json",
                lambda _: True,
            )
        assert removed == 0

    def test_keeps_non_matching(self, tmp_path):
        log = tmp_path / "log.json"
        _seed_log(log, [
            {"a": 1, "signal_source": "keeper"},
            {"a": 2, "signal_source": "drop_me"},
            {"a": 3, "signal_source": "keeper"},
        ])
        with patch(
            "core.automation.action_log."
            "is_test_environment",
            return_value=False,
        ):
            removed = prune_events_matching(
                log,
                lambda e: (
                    e.get("signal_source") == "drop_me"
                ),
            )
        assert removed == 1
        kept = load_log(log)
        assert len(kept) == 2
        for ev in kept:
            assert ev["signal_source"] == "keeper"

    def test_buggy_predicate_keeps_event(self, tmp_path):
        """A predicate that raises must NOT cause data loss."""
        log = tmp_path / "log.json"
        _seed_log(log, [
            {"a": 1}, {"a": 2}, {"a": 3},
        ])
        with patch(
            "core.automation.action_log."
            "is_test_environment",
            return_value=False,
        ):
            removed = prune_events_matching(
                log,
                lambda e: 1 / 0,  # explodes
            )
        assert removed == 0
        assert len(load_log(log)) == 3

    def test_test_environment_guard_zeros(self, tmp_path):
        """Pattern J: under pytest the prune short-circuits."""
        log = tmp_path / "log.json"
        _seed_log(log, [{"a": 1}, {"a": 2}])
        # Default: is_test_environment returns True under
        # PYTEST_CURRENT_TEST -> prune returns 0
        removed = prune_events_matching(
            log,
            lambda _: True,
        )
        assert removed == 0
        # Log unchanged
        assert len(load_log(log)) == 2


class TestPruneOlderThan:
    def test_drops_old_keeps_new(self, tmp_path):
        log = tmp_path / "log.json"
        now = time.time()
        _seed_log(log, [
            {"id": "old", "recorded_at": now - 7200},
            {"id": "new", "recorded_at": now - 60},
        ])
        with patch(
            "core.automation.action_log."
            "is_test_environment",
            return_value=False,
        ):
            removed = prune_events_older_than(log, 1.0)
        assert removed == 1
        kept = load_log(log)
        assert len(kept) == 1
        assert kept[0]["id"] == "new"

    def test_missing_recorded_at_treated_as_oldest(
        self, tmp_path,
    ):
        log = tmp_path / "log.json"
        _seed_log(log, [
            {"id": "no_ts"},
            {"id": "ts", "recorded_at": time.time()},
        ])
        with patch(
            "core.automation.action_log."
            "is_test_environment",
            return_value=False,
        ):
            removed = prune_events_older_than(log, 1.0)
        # Missing recorded_at -> recorded_at=0 -> old -> dropped
        assert removed == 1
        kept = load_log(log)
        assert kept[0]["id"] == "ts"
