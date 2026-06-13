"""W963-141: Pattern CD audit tests."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from engines._pattern_cd_audit import (
    PatternCDReport,
    _has_active_store_wrap,
    _is_active_store_call,
    _is_engine_run_call,
    _scan_file,
    audit_pattern_cd,
)


class TestEngineRunDetector:
    def test_engine_dot_run_matches(self):
        import ast
        tree = ast.parse("engine.run({})")
        # First expression's value is the Call
        call = tree.body[0].value
        assert _is_engine_run_call(call) is True

    def test_engine_instance_dot_run_matches(self):
        import ast
        tree = ast.parse("engine_instance.run(data)")
        assert _is_engine_run_call(
            tree.body[0].value,
        ) is True

    def test_other_run_calls_rejected(self):
        import ast
        for code in (
            "self.run(x)",
            "client.run(x)",
            "foo.bar(x)",
            "engine.fire(x)",
        ):
            tree = ast.parse(code)
            assert _is_engine_run_call(
                tree.body[0].value,
            ) is False


class TestActiveStoreCallDetector:
    def test_plain_active_store(self):
        import ast
        tree = ast.parse("active_store(sid)")
        assert _is_active_store_call(
            tree.body[0].value,
        ) is True

    def test_aliased_active_store(self):
        """W963-127 used `from core.context import
        active_store as _w963_127_active_store`. The
        audit must recognise that pattern."""
        import ast
        tree = ast.parse("_w963_127_active_store(sid)")
        assert _is_active_store_call(
            tree.body[0].value,
        ) is True

    def test_unrelated_calls_rejected(self):
        import ast
        for code in (
            "foo(x)",
            "active_user(x)",
            "client.do_thing(x)",
        ):
            tree = ast.parse(code)
            assert _is_active_store_call(
                tree.body[0].value,
            ) is False


class TestWrapDetection:
    def test_wrapped_engine_run_detected(self, tmp_path):
        """A correctly-wrapped function should yield
        has_wrap=True."""
        src = textwrap.dedent('''
            def handler(sid):
                with active_store(sid):
                    result = engine.run({})
        ''')
        p = tmp_path / "sample.py"
        p.write_text(src, encoding="utf-8")
        findings = _scan_file(p)
        assert len(findings) == 1
        assert findings[0].has_wrap is True

    def test_unwrapped_engine_run_detected(self, tmp_path):
        src = textwrap.dedent('''
            def handler(sid):
                result = engine.run({})
        ''')
        p = tmp_path / "sample.py"
        p.write_text(src, encoding="utf-8")
        findings = _scan_file(p)
        assert len(findings) == 1
        assert findings[0].has_wrap is False

    def test_wrap_in_nested_try_block(self, tmp_path):
        """A wrap with the engine.run inside a try/except
        nested under the with must still be detected."""
        src = textwrap.dedent('''
            def handler(sid):
                with active_store(sid):
                    try:
                        result = engine.run({})
                    except Exception:
                        pass
        ''')
        p = tmp_path / "sample.py"
        p.write_text(src, encoding="utf-8")
        findings = _scan_file(p)
        assert findings[0].has_wrap is True


class TestAuditEndToEnd:
    """The audit must pass on the current codebase."""

    def test_audit_no_violations(self):
        report = audit_pattern_cd()
        assert not report.has_violations, (
            "Pattern CD audit found unwrapped "
            "engine.run callsites: "
            f"{[(u.file, u.line, u.function) for u in report.unwrapped]}"
        )

    def test_audit_finds_strict_callsites(self):
        """At least the 4 known wrap callsites must
        show up as strict (cycle / webhook / approval /
        cluster-fire + others)."""
        report = audit_pattern_cd()
        # We expect 8 strict callsites currently
        # (cli + autonomous + webhook + approval).
        assert len(report.strict_callsites) >= 4
