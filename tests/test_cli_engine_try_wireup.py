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


class TestRunAll:
    """--all iterates every wired engine. Each engine resolves
    independently; failures don't abort the loop. Useful as a
    CI smoke gate."""

    def _build_report(self, engines):
        report = MagicMock()
        report.engines = []
        for spec in engines:
            wb = MagicMock()
            wb.name = spec["name"]
            wb.status = spec["status"]
            wb.writer_files = spec.get("writers", [])
            wb.opt_in_flags = spec.get("opt_ins", [])
            report.engines.append(wb)
        return report

    def test_all_dry_run_lists_every_wired_engine(self, cli):
        report = self._build_report([
            {
                "name": "loyalty",
                "status": "wired",
                "writers": ["discount_minter.py"],
                "opt_ins": ["apply_rewards"],
            },
            {
                "name": "nps_engine",
                "status": "advisory",
                "writers": [], "opt_ins": [],
            },
            {
                "name": "cart_recovery",
                "status": "wired",
                "writers": ["discount_minter.py"],
                "opt_ins": ["apply_recovery"],
            },
        ])
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(run_all=True),
            )
        assert code == 0
        # Advisory engine isn't iterated
        assert "nps_engine" not in out
        # Both wired engines appear
        assert "loyalty" in out
        assert "cart_recovery" in out
        # Apply-flag names visible
        assert "apply_rewards" in out
        assert "apply_recovery" in out

    def test_all_dry_run_json_envelope(self, cli):
        report = self._build_report([
            {
                "name": "loyalty",
                "status": "wired",
                "writers": ["discount_minter.py"],
                "opt_ins": ["apply_rewards"],
            },
        ])
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(run_all=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["summary"]["total_wired"] == 1
        assert data["summary"]["dry_run_ok"] == 1
        assert data["engines"][0]["engine"] == "loyalty"

    def test_all_engine_without_apply_flag_marked_error(self, cli):
        """An engine wired but with no apply_* opt-in flag is
        a bug -- the loop reports it as error, exits 1."""
        report = self._build_report([
            {
                "name": "broken",
                "status": "wired",
                "writers": ["something_applier.py"],
                "opt_ins": ["require_approval"],
            },
        ])
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(run_all=True),
            )
        assert code == 1
        assert "no_apply_flag" in out

    def test_all_yes_invokes_each_engine(
        self, cli, monkeypatch,
    ):
        # Safety guard added later requires the env var to
        # acknowledge --all --yes blast radius.
        monkeypatch.setenv(
            "SHOPAI_TRY_WIREUP_ALL_CONFIRM", "1",
        )
        report = self._build_report([
            {
                "name": "loyalty",
                "status": "wired",
                "writers": ["discount_minter.py"],
                "opt_ins": ["apply_rewards"],
            },
        ])
        fake_engine = MagicMock()
        fake_engine.run.return_value = {
            "status": "success",
            "data": {}, "meta": {}, "error": None,
        }
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ), patch(
            "engines.registry.get_engine",
            return_value=fake_engine,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(run_all=True, yes=True),
            )
        assert code == 0
        fake_engine.run.assert_called_once()
        # The engine's input had apply_rewards=True set
        engine_input = fake_engine.run.call_args[0][0]
        assert engine_input.get("apply_rewards") is True
        assert "EXECUTED" in out

    def test_all_yes_blocked_without_env_var(
        self, cli, monkeypatch,
    ):
        """Safety guard: --all --yes without
        SHOPAI_TRY_WIREUP_ALL_CONFIRM=1 should be refused
        BEFORE any writeback_audit call -- protects against
        accidental fleet-wide writes."""
        monkeypatch.delenv(
            "SHOPAI_TRY_WIREUP_ALL_CONFIRM", raising=False,
        )
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
        ) as audit_mock:
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(run_all=True, yes=True),
            )
        assert code == 1
        assert "blast radius" in out
        # The writeback audit (and any engine invocation)
        # shouldn't have been touched.
        audit_mock.assert_not_called()

    def test_all_yes_per_engine_failure_doesnt_abort(
        self, cli, monkeypatch,
    ):
        """If engine A raises during run, engine B should
        still be tried. Both reported in results."""
        monkeypatch.setenv(
            "SHOPAI_TRY_WIREUP_ALL_CONFIRM", "1",
        )
        report = self._build_report([
            {
                "name": "engine_a",
                "status": "wired",
                "writers": ["x_minter.py"],
                "opt_ins": ["apply_x"],
            },
            {
                "name": "engine_b",
                "status": "wired",
                "writers": ["y_minter.py"],
                "opt_ins": ["apply_y"],
            },
        ])

        good_engine = MagicMock()
        good_engine.run.return_value = {
            "status": "success",
            "data": {}, "meta": {}, "error": None,
        }

        def _get_engine_side_effect(name):
            if name == "engine_a":
                raise RuntimeError("A broken")
            return good_engine

        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=report,
        ), patch(
            "engines.registry.get_engine",
            side_effect=_get_engine_side_effect,
        ):
            out, code = _capture(
                cli._cmd_engine_try_wireup,
                _ns(run_all=True, yes=True),
            )
        # Loop continues; exit 1 since one failed
        assert code == 1
        # Both engines surfaced in output
        assert "engine_a" in out
        assert "engine_b" in out

    def test_no_engine_name_without_all_flag_refused(self, cli):
        """Without --all and without a positional engine_name,
        the command should refuse."""
        out, code = _capture(
            cli._cmd_engine_try_wireup,
            _ns(engine_name=None, run_all=False),
        )
        assert code == 1
        assert "engine_name is required" in out
        assert "or pass --all" in out
