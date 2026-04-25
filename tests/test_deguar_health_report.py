"""Tests for scripts/deguar_health_report.py.

Verifies:
  * Each audit module gets called via importlib + main()
  * stdout is captured, exit codes recorded
  * Verdict aggregation: 0+0+0 → READY, +1 → WARNINGS, +2 → BLOCKED
  * SystemExit + raised exceptions don't crash the wrapper
  * Markdown renders ok with collapsed details
  * --skip excludes named audits
  * --out '-' suppresses file write
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from scripts import deguar_health_report as mod


# ── _run_audit (the workhorse) ──────────────────────────


class TestRunAudit:
    def test_captures_stdout_and_rc(self):
        def fake_main(argv):
            print("LINE 1")
            print("LINE 2")
            return 0
        res = mod._run_audit("x", "purpose", fake_main)
        assert res.rc == 0
        assert "LINE 1" in res.output
        assert "LINE 2" in res.output
        assert res.status == "ok"

    def test_warning_exit_code(self):
        res = mod._run_audit(
            "x", "p", lambda argv: 1,
        )
        assert res.rc == 1
        assert res.status == "warning"

    def test_blocked_exit_code(self):
        res = mod._run_audit(
            "x", "p", lambda argv: 2,
        )
        assert res.rc == 2
        assert res.status == "blocked"

    def test_systemexit_captured(self):
        def fake(argv):
            print("partial")
            raise SystemExit(2)
        res = mod._run_audit("x", "p", fake)
        assert res.rc == 2
        assert "partial" in res.output

    def test_systemexit_zero(self):
        res = mod._run_audit(
            "x", "p", lambda argv: (_ for _ in ()).throw(SystemExit(0)),
        )
        assert res.rc == 0
        assert res.status == "ok"

    def test_exception_recorded_not_crashed(self):
        def boom(argv):
            print("before crash")
            raise RuntimeError("oh no")
        res = mod._run_audit("x", "p", boom)
        assert res.rc == -1
        assert res.status == "error"
        assert "before crash" in res.output
        assert "RuntimeError" in res.error
        assert "oh no" in res.error

    def test_none_return_treated_as_zero(self):
        """Some main() implementations return None implicitly."""
        res = mod._run_audit(
            "x", "p", lambda argv: None,
        )
        assert res.rc == 0


# ── HealthReport.verdict ────────────────────────────────


class TestVerdict:
    def _r(self, *codes: int) -> mod.HealthReport:
        audits = [
            mod.AuditResult(name=f"a{i}", purpose="", rc=c)
            for i, c in enumerate(codes)
        ]
        return mod.HealthReport(
            generated_at="2026-04-23", store="x", audits=audits,
        )

    def test_all_zero_ready(self):
        assert self._r(0, 0, 0).verdict == "READY"

    def test_any_one_warnings(self):
        assert self._r(0, 1, 0).verdict == "WARNINGS"

    def test_any_two_blocked(self):
        assert self._r(0, 2, 1).verdict == "BLOCKED"

    def test_error_blocked(self):
        assert self._r(0, -1).verdict == "BLOCKED"

    def test_only_skipped_unknown(self):
        a = mod.AuditResult(
            name="x", purpose="", skipped=True, skip_reason="-",
        )
        r = mod.HealthReport(
            generated_at="x", store="x", audits=[a],
        )
        assert r.verdict == "UNKNOWN"


# ── counts() ────────────────────────────────────────────


class TestCounts:
    def test_mixed(self):
        audits = [
            mod.AuditResult("a", "", rc=0),
            mod.AuditResult("b", "", rc=0),
            mod.AuditResult("c", "", rc=1),
            mod.AuditResult("d", "", rc=2),
            mod.AuditResult(
                "e", "", skipped=True, skip_reason="-",
            ),
        ]
        r = mod.HealthReport("d", "s", audits)
        c = r.counts()
        assert c["ok"] == 2
        assert c["warning"] == 1
        assert c["blocked"] == 1
        assert c["skipped"] == 1


# ── render_markdown / render_summary ────────────────────


class TestRendering:
    def _sample_report(self) -> mod.HealthReport:
        return mod.HealthReport(
            generated_at="2026-04-23",
            store="x.myshopify.com",
            audits=[
                mod.AuditResult(
                    "doctor", "config", rc=0,
                    output="ShopAI health: ok",
                ),
                mod.AuditResult(
                    "checkout_check",
                    "Payment + shipping + URL",
                    rc=2,
                    output="✗ no active payment provider",
                ),
                mod.AuditResult(
                    "live_audit", "Images",
                    skipped=True, skip_reason="--skip flag",
                ),
            ],
        )

    def test_markdown_includes_verdict(self):
        md = mod.render_markdown(self._sample_report())
        assert "BLOCKED" in md
        assert "x.myshopify.com" in md
        assert "Per-audit summary" in md

    def test_markdown_collapsed_details(self):
        md = mod.render_markdown(self._sample_report())
        assert "<details>" in md
        # Each audit gets one
        assert md.count("<details>") == 3
        assert md.count("</details>") == 3
        # Stdout content shows up inside ```text fence
        assert "no active payment provider" in md

    def test_markdown_skipped_section(self):
        md = mod.render_markdown(self._sample_report())
        assert "skipped" in md
        assert "--skip flag" in md

    def test_summary_one_line_per_audit(self):
        s = mod.render_summary(self._sample_report())
        # Header + verdict + blank + 3 audit lines = 6 lines
        assert s.count("\n") >= 5
        assert "doctor" in s
        assert "checkout_check" in s
        assert "BLOCKED" in s


# ── collect_audits with --skip ──────────────────────────


class TestCollectAudits:
    def test_skip_excludes_audit(self):
        with patch.object(mod, "_run_doctor",
                          return_value=mod.AuditResult(
                              "doctor", "p", rc=0,
                          )):
            audits = mod.collect_audits(skip=("checkout_check",))
        names = [a.name for a in audits]
        # checkout_check should appear but as skipped
        cc = [a for a in audits if a.name == "checkout_check"][0]
        assert cc.skipped
        assert cc.skip_reason == "--skip flag"

    def test_skip_doctor(self):
        # When doctor is in skip set, _run_doctor should NOT be
        # called at all (doctor entry omitted entirely)
        with patch.object(
            mod, "_run_doctor",
            side_effect=AssertionError("must not call"),
        ):
            audits = mod.collect_audits(skip=("doctor",))
        names = [a.name for a in audits]
        assert "doctor" not in names


# ── main() integration ──────────────────────────────────


class TestMain:
    def test_main_skip_all_writes_unknown_verdict(
        self, tmp_path, capsys,
    ):
        # Skip every audit → all skipped → verdict UNKNOWN → rc 2
        rc = mod.main([
            "--skip",
            "doctor,scope_audit,collection_check,webhook_check,"
            "tracking_check,checkout_check,live_audit",
            "--out", str(tmp_path),
        ])
        assert rc == 2  # UNKNOWN maps to 2
        # Markdown file written
        files = list(tmp_path.glob("*-health.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "UNKNOWN" in content

    def test_main_dash_out_skips_file(self, capsys, tmp_path):
        # Use --out - to suppress file write
        rc = mod.main([
            "--skip",
            "doctor,scope_audit,collection_check,webhook_check,"
            "tracking_check,checkout_check,live_audit",
            "--out", "-",
        ])
        # No files anywhere
        out = capsys.readouterr().out
        assert "Written:" not in out

    def test_main_summary_in_stdout(self, tmp_path, capsys):
        mod.main([
            "--skip",
            "doctor,scope_audit,collection_check,webhook_check,"
            "tracking_check,checkout_check,live_audit",
            "--out", str(tmp_path),
        ])
        out = capsys.readouterr().out
        assert "Deguar health" in out
        assert "Verdict:" in out

    def test_main_aggregates_real_results(self, tmp_path, capsys):
        """Inject fake audit modules so the wrapper aggregates a
        mix of OK + warning + blocked + reflects in verdict."""
        # Build fake module objects with a callable `main` that
        # returns the desired exit code.
        def make_fake(rc, output):
            class M:
                @staticmethod
                def main(argv):
                    print(output)
                    return rc
            return M

        original_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict,
        ) else __builtins__.__import__

        fake_modules = {
            "scripts.deguar_scope_audit": make_fake(0, "scopes ok"),
            "scripts.deguar_collection_check": make_fake(
                1, "thin",
            ),
            "scripts.deguar_webhook_check": make_fake(
                2, "missing webhooks",
            ),
            "scripts.deguar_tracking_check": make_fake(
                0, "pixel ok",
            ),
            "scripts.deguar_checkout_check": make_fake(
                0, "checkout ok",
            ),
            "scripts.deguar_live_audit": make_fake(
                0, "audit ok",
            ),
        }

        def my_import(name, *args, **kwargs):
            if name in fake_modules:
                return fake_modules[name]
            return original_import(name, *args, **kwargs)

        with patch.object(
            mod, "_run_doctor",
            return_value=mod.AuditResult(
                "doctor", "config", rc=0, output="ok",
            ),
        ), patch("builtins.__import__", side_effect=my_import):
            rc = mod.main([
                "--out", str(tmp_path),
            ])
        # webhook_check returned 2 → BLOCKED
        assert rc == 2
        out = capsys.readouterr().out
        assert "BLOCKED" in out
        # All 7 audits should appear in the table
        files = list(tmp_path.glob("*-health.md"))
        md = files[0].read_text()
        for name in (
            "doctor", "scope_audit", "collection_check",
            "webhook_check", "tracking_check",
            "checkout_check", "live_audit",
        ):
            assert name in md
