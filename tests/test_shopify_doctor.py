"""Tests for ``shopai shopify-doctor`` — aggregate health
check across all four institutional protection layers.

Verifies:
  - All sections render in pass + fail + skipped + unavailable
    states
  - Overall exit code reflects per-section status
  - --skip-live correctly skips the live check
  - --json emits a structured envelope
  - A single section failure fails the doctor
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
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
    defaults = dict(json=False, skip_live=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Live run ──────────────────────────────────────────────────


class TestLiveRun:

    def test_live_doctor_exits_0_with_skip_live(self, cli):
        """The live registry / dispatcher state passes all four
        gates today. With --skip-live, no Shopify call is
        attempted."""
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(skip_live=True),
        )
        assert code == 0
        assert "Overall: OK" in out
        # All four sections render
        assert "[pass] Pattern K" in out
        assert "[pass] OAuth scope" in out
        assert "[pass] Pattern Y" in out
        assert "[skip] Live scope" in out

    def test_live_doctor_default_renders_skip_when_no_creds(
        self, cli,
    ):
        """Without --skip-live, the doctor still tries to hit
        the live API. In dev environments without configured
        creds, the live section renders as 'skipped' (apps
        adapter not configured) rather than failing the doctor."""
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(),
        )
        assert code == 0
        assert "[skip] Live scope" in out
        assert "Overall: OK" in out


# ─── JSON envelope ─────────────────────────────────────────────


class TestJson:

    def test_json_envelope_shape(self, cli):
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        # W937: roster grows over time; assert subset semantics
        # so new sections (e.g. wireup_resolve) don't break the
        # test as the doctor expands.
        base = {
            "pattern_k_dispatchers",
            "oauth_scope_coverage",
            "pattern_y_capabilities",
            "pattern_i_engine_capabilities",
            "pattern_j_test_pollution",
            "pattern_z_writer_recorder",
            "live_scope_drift",
            "live_webhook_drift",
            "engines_writebacks",
        }
        assert base <= set(data["sections"].keys())

    def test_json_pattern_k_section(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor, _ns(json=True, skip_live=True),
        )
        data = json.loads(out)
        section = data["sections"]["pattern_k_dispatchers"]
        assert section["status"] == "pass"
        assert section["missing"] == []
        assert section["orphaned"] == []

    def test_json_oauth_section(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor, _ns(json=True, skip_live=True),
        )
        data = json.loads(out)
        section = data["sections"]["oauth_scope_coverage"]
        assert section["status"] == "pass"
        assert section["undeclared_adapters"] == []
        assert section["scope_independent_count"] >= 0

    def test_json_pattern_y_section(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor, _ns(json=True, skip_live=True),
        )
        data = json.loads(out)
        section = data["sections"]["pattern_y_capabilities"]
        assert section["status"] == "pass"
        assert section["unclaimed"] == []

    def test_json_skip_live_section(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor, _ns(json=True, skip_live=True),
        )
        data = json.loads(out)
        section = data["sections"]["live_scope_drift"]
        assert section["status"] == "skipped"
        assert "--skip-live" in section["reason"]

    def test_json_first_char_is_brace(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor, _ns(json=True),
        )
        assert out.strip()[0] == "{"


# ─── Section failure propagation ───────────────────────────────


class TestFailurePropagation:

    def test_pattern_k_failure_fails_doctor(self, cli):
        """Patch the Pattern K audit to return gaps — doctor
        must exit 1 even though everything else is clean."""
        from core.approval.coverage_audit import AuditReport
        bad_report = AuditReport(
            enqueued=[],
            registered=[],
            missing={"missing_action"},
            orphaned=set(),
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=bad_report,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor,
                _ns(skip_live=True),
            )
        assert code == 1
        assert "FAILED" in out
        assert "[FAIL] Pattern K" in out

    def test_oauth_failure_fails_doctor(self, cli):
        from core.adapters.shopify.scope_registry import ScopeManifest
        bad = ScopeManifest(
            all_scopes=frozenset(),
            by_scope={},
            by_adapter={"a": []},
            undeclared_adapters=["a"],
            scope_independent_adapters=[],
            total_adapters=1,
        )
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor,
                _ns(skip_live=True),
            )
        assert code == 1
        assert "[FAIL] OAuth scope" in out

    def test_pattern_y_failure_fails_doctor(self, cli):
        from core.adapters.coverage_audit import CapabilityCoverageReport
        bad = CapabilityCoverageReport(
            total_shopify_capabilities=380,
            claimed_count=379,
            unclaimed=["SHOPIFY_MISSING"],
            orphan_claims=[],
            multi_claimed={},
            has_gaps=True,
        )
        with patch(
            "core.adapters.coverage_audit.audit_capability_coverage",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor,
                _ns(skip_live=True),
            )
        assert code == 1
        assert "[FAIL] Pattern Y" in out

    def test_live_failure_fails_doctor(self, cli):
        from core.adapters.shopify.scope_health import ScopeHealthReport
        bad = ScopeHealthReport(
            granted_scopes=frozenset(),
            required_scopes=frozenset({"read_orders"}),
            missing_from_app=["read_orders"],
            extra_in_app=[],
            is_healthy=False,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(),
            )
        assert code == 1
        assert "[FAIL] Live scope" in out


# ─── Best-effort resilience ───────────────────────────────────


class TestResilience:

    def test_individual_audit_exception_renders_unavailable(
        self, cli,
    ):
        """A module-level exception in one of the audits surfaces
        as ``status=unavailable`` for that section but doesn't
        crash the doctor. Other sections still report."""
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor,
                _ns(skip_live=True),
            )
        # Pattern K reports unavailable, other sections still pass
        assert "[??] Pattern K" in out
        # Unavailable is NOT a failure — overall stays OK
        assert code == 0
        assert "Overall: OK" in out

    def test_live_unconfigured_doesnt_fail(self, cli):
        """When the apps adapter isn't configured (live check
        returns None), the doctor reports skipped — not fail."""
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(),
            )
        assert code == 0
        assert "[skip] Live scope" in out
        assert "not configured" in out


# ─── Extras warning (live healthy + extras) ───────────────────


class TestLiveWarnings:

    def test_live_healthy_with_extras_renders_warning(self, cli):
        """Healthy + extras → pass with a warning line. Doctor
        stays at OK."""
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({
                "read_orders", "read_unused",
            }),
            required_scopes=frozenset({"read_orders"}),
            missing_from_app=[],
            extra_in_app=["read_unused"],
            is_healthy=True,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(),
            )
        assert code == 0
        assert "[pass] Live scope" in out
        assert "warning" in out.lower()
        assert "read_unused" not in out  # not enumerated in text
        # but JSON includes them
        out_json, _ = _capture(
            cli._cmd_shopify_doctor,
            _ns(json=True),
        )
        # Patch is gone after exiting context — re-patch
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out_json, _ = _capture(
                cli._cmd_shopify_doctor,
                _ns(json=True),
            )
        data = json.loads(out_json)
        assert "read_unused" in data["sections"]["live_scope_drift"]["extra_in_app"]


# ─── Engines-writebacks section (PR #188) ──────────────────────


class TestEnginesWritebacksSection:
    """The 6th doctor section reports Phase 6/7 writeback
    coverage. Informational by default — never fails the
    doctor; flags 'partial' wireups as a warning."""

    def test_section_appears_in_text(self, cli):
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(skip_live=True),
        )
        assert code == 0
        assert "Engine writebacks" in out
        # Live audit has wired + advisory engines
        assert "wired" in out

    def test_section_appears_in_json(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor,
            _ns(json=True, skip_live=True),
        )
        data = json.loads(out)
        assert "engines_writebacks" in data["sections"]
        section = data["sections"]["engines_writebacks"]
        assert section["status"] in {"info", "warn"}
        assert section["total_engines"] >= 100
        assert section["wired"] >= 20

    def test_info_status_doesnt_fail_doctor(self, cli):
        """Advisory engines are legitimate. The doctor must
        stay at OK even with ~113 advisory engines today."""
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(skip_live=True),
        )
        assert code == 0
        assert "Overall: OK" in out

    def test_partial_engine_renders_warn(self, cli):
        """A partial wireup is a real gap. Section renders
        [WARN] but doesn't fail the doctor overall — partial
        is informational, not fatal."""
        from engines._writeback_audit import (
            EngineWritebackStatus,
            WritebackCoverageReport,
        )
        fake_report = WritebackCoverageReport(
            engines=[
                EngineWritebackStatus(
                    name="half_wired", has_flow=True,
                    writer_files=["x_applier.py"],
                    opt_in_flags=[],
                    status="partial",
                ),
            ],
            wired_count=0, advisory_count=0, partial_count=1,
            total_engines=1,
        )
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            return_value=fake_report,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        # Warn appears, but doctor stays OK (partial is info)
        assert "[WARN] Engine writebacks" in out
        assert code == 0

    def test_audit_failure_renders_unavailable(self, cli):
        """If the writeback-audit module itself raises, the
        doctor's section renders [??] and the overall stays OK."""
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        assert "[??] Engine writebacks" in out
        # Doctor overall stays OK — audit failure is informational
        assert code == 0


# ─── Remediation hints (PR follows #191) ──────────────────────


class TestRemediationHints:
    """When a section fails, the doctor must surface a one-line
    'fix:' hint so the operator knows what to change. Same
    pattern as `shopai capabilities-audit`'s remediation line."""

    def test_pattern_k_fail_shows_fix_hint(self, cli):
        from core.approval.coverage_audit import AuditReport
        bad = AuditReport(
            enqueued=[],
            registered=[],
            missing={"missing_action"},
            orphaned=set(),
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=bad,
        ):
            out, _ = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        assert "fix:" in out
        assert "core/approval/dispatchers.py" in out

    def test_oauth_fail_shows_fix_hint(self, cli):
        from core.adapters.shopify.scope_registry import ScopeManifest
        bad = ScopeManifest(
            all_scopes=frozenset(),
            by_scope={},
            by_adapter={"foo_adapter": []},
            undeclared_adapters=["foo_adapter"],
            scope_independent_adapters=[],
            total_adapters=1,
        )
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=bad,
        ):
            out, _ = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        assert "fix:" in out
        assert "required_scopes" in out
        # First gap is enumerated in the FAIL line so operators
        # don't have to re-run a separate audit for the first hit
        assert "foo_adapter" in out

    def test_pattern_y_fail_shows_fix_hint(self, cli):
        from core.adapters.coverage_audit import CapabilityCoverageReport
        bad = CapabilityCoverageReport(
            total_shopify_capabilities=380,
            claimed_count=379,
            unclaimed=["SHOPIFY_MISSING"],
            orphan_claims=[],
            multi_claimed={},
            has_gaps=True,
        )
        with patch(
            "core.adapters.coverage_audit.audit_capability_coverage",
            return_value=bad,
        ):
            out, _ = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        assert "fix:" in out
        assert "core/adapters/shopify" in out

    def test_live_scope_fail_shows_reinstall_hint(self, cli):
        from core.adapters.shopify.scope_health import ScopeHealthReport
        bad = ScopeHealthReport(
            granted_scopes=frozenset(),
            required_scopes=frozenset({"read_orders"}),
            missing_from_app=["read_orders"],
            extra_in_app=[],
            is_healthy=False,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=bad,
        ):
            out, _ = _capture(
                cli._cmd_shopify_doctor, _ns(),
            )
        assert "fix:" in out
        assert "re-install" in out.lower()
        # Sample of missing scopes appears in the FAIL line
        assert "read_orders" in out

    def test_pattern_j_section_renders_in_text(self, cli):
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(skip_live=True),
        )
        assert code == 0
        assert "Pattern J test pollution" in out

    def test_pattern_z_section_renders_in_text(self, cli):
        out, code = _capture(
            cli._cmd_shopify_doctor, _ns(skip_live=True),
        )
        assert code == 0
        assert "Pattern Z writer-recorder" in out

    def test_pattern_j_failure_fails_doctor(self, cli):
        from engines._pattern_j_audit import (
            PatternJReport,
            WriteSite,
        )
        bad = PatternJReport(
            recorder_sites=[],
            guarded_sites=[],
            unguarded_sites=[
                WriteSite(
                    file="engines/x/flow.py",
                    lineno=42,
                    method="create_from_decision",
                    receiver_expr="mi",
                    module_path="/abs/x/flow.py",
                ),
            ],
            scanned_modules=10,
        )
        with patch(
            "engines._pattern_j_audit.audit_pattern_j",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        assert code == 1
        assert "[FAIL] Pattern J" in out
        assert "engines/x/flow.py:42" in out
        # Remediation hint surfaces
        assert "fix:" in out
        assert "_writeback_recorder" in out

    def test_pattern_z_failure_fails_doctor(self, cli):
        from engines._pattern_z_audit import (
            PatternZReport,
            WriterAuditSite,
        )
        bad = PatternZReport(
            scanned_writers=1,
            clean_writers=[],
            missing_recorder=[
                WriterAuditSite(
                    file="engines/bad/foo_applier.py",
                    mutation_calls=("execute",),
                    has_recorder_import=False,
                ),
            ],
            skipped_no_mutation=[],
        )
        with patch(
            "engines._pattern_z_audit.audit_pattern_z",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor, _ns(skip_live=True),
            )
        assert code == 1
        assert "[FAIL] Pattern Z" in out
        assert "engines/bad/foo_applier.py" in out
        # Remediation hint surfaces
        assert "fix:" in out
        assert "record_writeback" in out

    def test_webhook_fail_shows_gdpr_callout(self, cli):
        """GDPR-mandatory missing topics get a separate, louder
        callout because they block public-distribution review."""
        from core.feedback.webhook_health import WebhookHealthReport
        bad = WebhookHealthReport(
            registered_topics=frozenset(),
            declared_topics=frozenset({
                "customers/data_request",
                "customers/redact",
            }),
            missing_on_app=[
                "customers/data_request",
                "customers/redact",
            ],
            extra_on_app=[],
            gdpr_missing=[
                "customers/data_request",
                "customers/redact",
            ],
            is_healthy=False,
        )
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=bad,
        ):
            out, _ = _capture(
                cli._cmd_shopify_doctor, _ns(),
            )
        assert "GDPR topics missing" in out
        assert "REJECT" in out
        # Both missing GDPR topics enumerated
        assert "customers/data_request" in out
        assert "customers/redact" in out
        # General fix hint also present
        assert "shopify-prepare-deploy" in out
