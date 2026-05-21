"""Tests for ``engines.fraud_detection.blacklist_checker``
-- silent-fail fix on blacklist load.

Before: a corrupt / unreadable ``blacklists.json`` silently
returned an empty structure, effectively disabling all fraud
checks. ``check_blacklists`` then PASSED everything (no
matches against an empty list). The blindspot is security-
relevant: known-bad emails / IPs could go through unflagged
for weeks before someone noticed.

After: the failure logs at warning with the file path and
exception. Return contract preserved (still returns empty
blacklist on failure to keep fraud-check call sites alive).
"""
from __future__ import annotations

import json
import logging

import pytest


class TestBlacklistLoadLogging:

    def test_corrupt_file_logs_warning(self, tmp_path, caplog):
        """A blacklists.json that fails JSON parse should warn."""
        from engines.fraud_detection import blacklist_checker

        corrupt = tmp_path / "blacklists.json"
        corrupt.write_text("not valid json {{{")
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.WARNING):
            mp.setattr(
                blacklist_checker,
                "_BLACKLIST_PATH",
                str(corrupt),
            )
            result = blacklist_checker._load_blacklists()
        # Behavior contract: empty blacklist on failure
        assert result == {
            "emails": [], "ips": [],
            "phones": [], "address_hashes": [],
        }
        log_messages = [r.message for r in caplog.records]
        assert any(
            "_load_blacklists failed" in m
            and "blacklists.json" in m
            and "fraud checks effectively disabled" in m
            for m in log_messages
        )

    def test_open_failure_logs_warning(self, tmp_path, caplog):
        """If open() raises after isfile() passes (e.g. file
        was deleted between the check and the open), the
        failure should log not silently drop."""
        from engines.fraud_detection import blacklist_checker
        from unittest.mock import patch

        # Create a real file so isfile() returns True
        target = tmp_path / "blacklists.json"
        target.write_text("{}")
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.WARNING):
            mp.setattr(
                blacklist_checker,
                "_BLACKLIST_PATH",
                str(target),
            )
            # Make open() raise inside the try block
            with patch(
                "builtins.open",
                side_effect=OSError("permission denied"),
            ):
                result = blacklist_checker._load_blacklists()
        assert result["emails"] == []
        msgs = [r.message for r in caplog.records]
        assert any(
            "_load_blacklists failed" in m
            and "permission denied" in m
            for m in msgs
        )

    def test_missing_file_silent(self, tmp_path, caplog):
        """Missing file is normal first-run -- no warning."""
        from engines.fraud_detection import blacklist_checker
        missing = tmp_path / "does_not_exist.json"
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.DEBUG):
            mp.setattr(
                blacklist_checker,
                "_BLACKLIST_PATH",
                str(missing),
            )
            result = blacklist_checker._load_blacklists()
        assert result["emails"] == []
        # No log records for the normal missing-file path
        assert caplog.records == []

    def test_valid_file_loaded_no_log(self, tmp_path, caplog):
        from engines.fraud_detection import blacklist_checker
        good = tmp_path / "blacklists.json"
        good.write_text(json.dumps({
            "emails": ["bad@example.com"],
            "ips": [],
            "phones": [],
            "address_hashes": [],
        }))
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.WARNING):
            mp.setattr(
                blacklist_checker,
                "_BLACKLIST_PATH",
                str(good),
            )
            result = blacklist_checker._load_blacklists()
        assert "bad@example.com" in result["emails"]
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []
