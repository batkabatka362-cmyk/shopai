"""Tests for the Pattern I engine-capability parity audit + CLI.

Pattern I documents the silent failure mode caught in PR #40:
an engine hydrator references a capability name string that
exists on the Capability enum but no adapter claims (silent
unroutable), or a name that doesn't exist on the enum at all
(typo trap that mocked unit tests miss).

Tests cover:
  - The audit module's two failure classifications + happy path
  - The live audit (PR #40 fix → no regressions today)
  - CLI text + JSON output for pass / fail
  - Synthetic engine-tree audit isolates the AST walker so tests
    don't depend on the production engines/ tree contents
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
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
    defaults = dict(json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── audit_engine_capabilities() ──────────────────────────────


class TestLiveAudit:

    def test_live_audit_passes(self):
        """PR #40 fixed the documented gap; this is a regression
        guard against new typos or unclaimed-capability uses
        landing on main."""
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        report = audit_engine_capabilities()
        assert report.has_gaps is False, (
            f"unknown={report.unknown_enum_member}, "
            f"unclaimed={report.unclaimed_by_adapter}"
        )
        # Audit found refs — sanity that the AST walker is actually
        # finding capability_name= kwargs.
        assert report.total_refs > 0
        assert report.distinct_capabilities > 0


class TestSyntheticTree:
    """Audit a small synthetic engines/ tree so the failure
    classifications can be exercised without modifying the real
    production engines/."""

    def _make_engine(self, tmp_path: Path, name: str, body: str):
        engine_dir = tmp_path / name
        engine_dir.mkdir()
        (engine_dir / "__init__.py").write_text("", encoding="utf-8")
        (engine_dir / "flow.py").write_text(body, encoding="utf-8")
        return engine_dir

    def test_typo_surfaces_as_unknown_enum_member(self, tmp_path):
        """A capability_name= that doesn't exist on the Capability
        enum is the typo trap. PR #40 was caught by similar
        reasoning — this surfaces it as a hard fail."""
        self._make_engine(
            tmp_path, "bad_typo_engine",
            'def x():\n'
            '    return hydrate(capability_name="SHOPIFY_NOT_REAL")\n',
        )
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        report = audit_engine_capabilities(engines_root=tmp_path)
        assert len(report.unknown_enum_member) == 1
        ref = report.unknown_enum_member[0]
        assert ref.capability_name == "SHOPIFY_NOT_REAL"
        assert ref.engine == "bad_typo_engine"
        assert ref.lineno == 2
        assert report.has_gaps is True

    def test_real_enum_unclaimed_by_adapter(self, tmp_path):
        """Enum value exists but every adapter is patched away.
        Surfaces as unclaimed (vs unknown)."""
        self._make_engine(
            tmp_path, "good_call_engine",
            'def x():\n'
            '    return hydrate(capability_name="SHOPIFY_LIST_ORDERS")\n',
        )
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        from core.adapters.shopify import bootstrap
        # Empty adapter set → SHOPIFY_LIST_ORDERS is on the enum
        # but no adapter claims it
        with patch.object(
            bootstrap, "_SHOPIFY_ADAPTER_CLASSES", (),
        ):
            report = audit_engine_capabilities(engines_root=tmp_path)
        # SHOPIFY_LIST_ORDERS exists on the enum, so it's NOT
        # unknown — it's unclaimed
        assert len(report.unknown_enum_member) == 0
        assert len(report.unclaimed_by_adapter) == 1
        ref = report.unclaimed_by_adapter[0]
        assert ref.capability_name == "SHOPIFY_LIST_ORDERS"
        assert report.has_gaps is True

    def test_happy_path_synthetic(self, tmp_path):
        """A real enum + a real adapter claim → clean audit."""
        self._make_engine(
            tmp_path, "clean_engine",
            'def x():\n'
            '    return hydrate(capability_name="SHOPIFY_LIST_ORDERS")\n',
        )
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        report = audit_engine_capabilities(engines_root=tmp_path)
        # SHOPIFY_LIST_ORDERS is claimed in the live registry
        assert report.has_gaps is False
        assert report.total_refs == 1
        assert report.distinct_capabilities == 1

    def test_non_string_capability_name_ignored(self, tmp_path):
        """A variable / non-literal capability_name= isn't a
        string the AST walker can resolve — must be silently
        ignored, not flagged as unknown."""
        self._make_engine(
            tmp_path, "dynamic_engine",
            'CAP = "SHOPIFY_LIST_ORDERS"\n'
            'def x():\n'
            '    return hydrate(capability_name=CAP)\n',
        )
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        report = audit_engine_capabilities(engines_root=tmp_path)
        # No refs were collected because the value is a Name not
        # a Constant — the audit can't reason about it, so it
        # stays silent rather than flagging a false positive
        assert report.total_refs == 0

    def test_empty_tree_returns_empty(self, tmp_path):
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        report = audit_engine_capabilities(engines_root=tmp_path)
        assert report.total_refs == 0
        assert report.has_gaps is False

    def test_nonexistent_path_returns_empty(self, tmp_path):
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        report = audit_engine_capabilities(
            engines_root=tmp_path / "does_not_exist",
        )
        assert report.total_refs == 0
        assert report.has_gaps is False


# ─── CLI ─────────────────────────────────────────────────────


class TestCli:

    def test_live_audit_exits_0(self, cli):
        out, code = _capture(
            cli._cmd_engines_capability_audit, _ns(),
        )
        assert code == 0
        assert "OK" in out
        assert "capability_name=" in out

    def test_typo_exits_1(self, cli, tmp_path):
        # Patch the underlying audit to return a synthetic fail
        from engines._engine_capability_audit import (
            EngineCapabilityRef,
            EngineCapabilityReport,
        )
        bad = EngineCapabilityReport(
            refs=(
                EngineCapabilityRef(
                    engine="bad",
                    file="bad/flow.py",
                    lineno=42,
                    capability_name="SHOPIFY_BAD_NAME",
                ),
            ),
            unknown_enum_member=[
                EngineCapabilityRef(
                    engine="bad",
                    file="bad/flow.py",
                    lineno=42,
                    capability_name="SHOPIFY_BAD_NAME",
                ),
            ],
            unclaimed_by_adapter=[],
            total_refs=1,
            distinct_capabilities=1,
        )
        with patch(
            "engines._engine_capability_audit."
            "audit_engine_capabilities",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_engines_capability_audit, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "SHOPIFY_BAD_NAME" in out
        assert "Fix:" in out

    def test_json_pass(self, cli):
        out, code = _capture(
            cli._cmd_engines_capability_audit, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["total_refs"] > 0
        assert data["unknown_enum_member"] == []
        assert data["unclaimed_by_adapter"] == []

    def test_json_fail(self, cli):
        from engines._engine_capability_audit import (
            EngineCapabilityRef,
            EngineCapabilityReport,
        )
        bad = EngineCapabilityReport(
            refs=(),
            unknown_enum_member=[],
            unclaimed_by_adapter=[
                EngineCapabilityRef(
                    engine="x",
                    file="x/flow.py",
                    lineno=1,
                    capability_name="SHOPIFY_LIST_ORDERS",
                ),
            ],
            total_refs=1,
            distinct_capabilities=1,
        )
        with patch(
            "engines._engine_capability_audit."
            "audit_engine_capabilities",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_engines_capability_audit, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert len(data["unclaimed_by_adapter"]) == 1
        assert (
            data["unclaimed_by_adapter"][0]["capability_name"]
            == "SHOPIFY_LIST_ORDERS"
        )

    def test_module_failure_renders_unavailable(self, cli):
        with patch(
            "engines._engine_capability_audit."
            "audit_engine_capabilities",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_engines_capability_audit, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()


# ─── Doctor section integration ─────────────────────────────


class TestDoctorSection:

    def test_pattern_i_section_in_text(self, cli):
        out, code = _capture(
            cli._cmd_shopify_doctor,
            argparse.Namespace(json=False, skip_live=True),
        )
        assert code == 0
        assert "Pattern I engine capabilities" in out

    def test_pattern_i_section_in_json(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor,
            argparse.Namespace(json=True, skip_live=True),
        )
        data = json.loads(out)
        assert "pattern_i_engine_capabilities" in data["sections"]
        section = data["sections"]["pattern_i_engine_capabilities"]
        assert section["status"] == "pass"
        assert section["total_refs"] > 0

    def test_pattern_i_failure_fails_doctor(self, cli):
        """A Pattern I gap must flip overall_ok to False, exit 1."""
        from engines._engine_capability_audit import (
            EngineCapabilityRef,
            EngineCapabilityReport,
        )
        bad = EngineCapabilityReport(
            refs=(),
            unknown_enum_member=[
                EngineCapabilityRef(
                    engine="x",
                    file="x/flow.py",
                    lineno=1,
                    capability_name="SHOPIFY_TYPO",
                ),
            ],
            unclaimed_by_adapter=[],
            total_refs=1,
            distinct_capabilities=1,
        )
        with patch(
            "engines._engine_capability_audit."
            "audit_engine_capabilities",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor,
                argparse.Namespace(json=False, skip_live=True),
            )
        assert code == 1
        assert "[FAIL] Pattern I" in out
        assert "SHOPIFY_TYPO" in out
        assert "fix:" in out
