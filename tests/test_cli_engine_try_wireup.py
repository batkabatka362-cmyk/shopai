"""Tests for ``shopai engine try-wireup <name>``.

The smoke-test CLI for Phase 7 wireups. Resolves the engine's
apply_* opt-in flag from writeback_audit and invokes the engine
with the flag set. DRY-RUN by default; --yes actually runs.

Coverage:
  1. Wired engine + no --yes -> DRY-RUN renders the plan
     (apply_flag, writers, data_keys).
  2. Advisory engine refused with clear error.
  3. Unknown engine name refused.
  4. --yes invokes the engine + surfaces the writer's
     results-array field (minted_codes / apply_results / etc).
  5. Engine raise during --yes surfaces clean error + exit 1.
  6. --params JSON merged into engine input.
  7. Invalid --params JSON surfaces clean error.
  8. JSON envelope shape (dry-run + executed).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "shopai_cli", "cli.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        engine_name="churn_prediction",
        yes=False,
        store=None,
        params="{}",
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _wired_report(engine_name="churn_prediction"):
    """Synthesize a writeback_audit report with one wired
    engine matching engine_name."""
    return MagicMock(
        engines=[
            MagicMock(
                name=engine_name,
                status="wired",
                writer_files=["discount_minter.py"],
                opt_in_flags=["apply_retention_codes"],
            ),
        ],
    )


class TestDryRun:

    def test_wired_engine_dry_run_renders_plan(self, cli):
        report = MagicMock()
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report.engines = [wb_entry]

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup, _ns(),
            )
        assert code == 0
        assert "DRY-RUN" in out
        assert "apply_retention_codes" in out
        assert "discount_minter.py" in out
        assert "Pass --yes to actually invoke" in out

    def test_json_dry_run_envelope(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "dry_run"
        assert data["plan"]["engine"] == "churn_prediction"
        assert data["plan"]["apply_flag"] == "apply_retention_codes"


class TestRefusalPaths:

    def test_advisory_engine_refused(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "nps_engine"
        wb_entry.status = "advisory"
        wb_entry.writer_files = []
        wb_entry.opt_in_flags = []
        report = MagicMock()
        report.engines = [wb_entry]

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(engine_name="nps_engine"),
            )
        assert code == 1
        assert "advisory" in out
        assert "try-wireup only supports wired engines" in out

    def test_unknown_engine_refused(self, cli):
        report = MagicMock()
        report.engines = []

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(engine_name="ghost"),
            )
        assert code == 1
        assert "unknown engine: ghost" in out

    def test_empty_engine_name_refused(self, cli):
        out, code = _capture(
            cli._cmd_engine_try_wireup,
            _ns(engine_name=""),
        )
        assert code == 1
        assert "engine_name is required" in out


class TestParamsHandling:

    def test_extra_params_merged_into_input(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, _ = _capture(
                cli._cmd_engine_try_wireup,
                _ns(params='{"niche": "apparel"}', json=True),
            )
        data = json.loads(out)
        assert "niche" in data["plan"]["data_keys"]

    def test_invalid_params_json_refused(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(params="not json"),
            )
        assert code == 1
        assert "not valid JSON" in out

    def test_non_dict_params_refused(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(params='["a", "b"]'),
            )
        assert code == 1
        assert "must be a JSON object" in out


class TestExecute:

    def test_yes_invokes_engine(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        fake_engine = MagicMock()
        fake_engine.run.return_value = {
            "status": "success",
            "data": {"minted_codes": []},
            "meta": {}, "error": None,
        }

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ), patch(
            "engines.registry.get_engine",
            return_value=fake_engine,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup, _ns(yes=True),
            )
        assert code == 0
        assert "EXECUTED" in out
        fake_engine.run.assert_called_once()
        # The apply_* flag must be in the engine input
        call_args = fake_engine.run.call_args[0][0]
        assert call_args.get("apply_retention_codes") is True

    def test_engine_raise_clean_error(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        fake_engine = MagicMock()
        fake_engine.run.side_effect = RuntimeError("data missing")

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ), patch(
            "engines.registry.get_engine",
            return_value=fake_engine,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup, _ns(yes=True),
            )
        assert code == 1
        assert "Engine raised: data missing" in out

    def test_yes_json_envelope_includes_result(self, cli):
        wb_entry = MagicMock()
        wb_entry.name = "churn_prediction"
        wb_entry.status = "wired"
        wb_entry.writer_files = ["discount_minter.py"]
        wb_entry.opt_in_flags = ["apply_retention_codes"]
        report = MagicMock()
        report.engines = [wb_entry]

        fake_engine = MagicMock()
        fake_engine.run.return_value = {
            "status": "success",
            "data": {
                "minted_codes": [{"code": "RETAIN1"}],
            },
            "meta": {}, "error": None,
        }

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ), patch(
            "engines.registry.get_engine",
            return_value=fake_engine,
        ):
            out, _ = _capture(
                cli._cmd_engine_try_wireup,
                _ns(yes=True, json=True),
            )
        data = json.loads(out)
        assert data["status"] == "ok"
        assert (
            data["result"]["data"]["minted_codes"][0]["code"]
            == "RETAIN1"
        )
