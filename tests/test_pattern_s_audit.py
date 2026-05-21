"""Tests for ``engines._pattern_s_audit``.

The audit scans for ``except: pass`` blocks whose body is
EXACTLY one ``pass`` statement -- the most damaging silent-
swallow pattern. PRs #475-#478 each fixed one of these
hand-found; this audit makes the rest findable systematically.
"""
from __future__ import annotations

import textwrap

import pytest


def _write(tmp_path, name: str, src: str) -> None:
    (tmp_path / name).write_text(textwrap.dedent(src))


class TestPatternSAudit:

    def test_finds_bare_pass(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is True
        assert len(report.silent_sites) == 1
        site = report.silent_sites[0]
        assert site.file == "mod.py"
        assert site.lineno == 5

    def test_skips_except_with_logger_call(self, tmp_path):
        """An except body with a logger call is NOT silent --
        the audit ignores it."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def f():
                try:
                    do_thing()
                except Exception as exc:
                    logging.warning("oops: %s", exc)
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_skips_except_with_re_raise(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f():
                try:
                    do_thing()
                except Exception:
                    raise
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_skips_except_with_return(self, tmp_path):
        """An except body that returns something (not just pass)
        is also not flagged -- the operator at least sees a
        contract-shaped result. PR #478's gap was different
        (return + no log) and is left for the per-call audit."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f():
                try:
                    do_thing()
                except Exception:
                    return None
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_skips_tests_directory(self, tmp_path):
        """Test files legitimately use except: pass as scaffolding."""
        from engines._pattern_s_audit import audit_pattern_s
        sub = tmp_path / "tests"
        sub.mkdir()
        (sub / "test_x.py").write_text(textwrap.dedent('''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''').strip())
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_skips_scripts_directory(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        sub = tmp_path / "scripts"
        sub.mkdir()
        (sub / "x.py").write_text(textwrap.dedent('''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''').strip())
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_skips_pycache(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        sub = tmp_path / "__pycache__"
        sub.mkdir()
        (sub / "x.py").write_text(textwrap.dedent('''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''').strip())
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_skips_whitelist(self, tmp_path):
        """``utils/logger.py`` is whitelisted (can't log a log
        handler's own failure)."""
        from engines._pattern_s_audit import audit_pattern_s
        sub = tmp_path / "utils"
        sub.mkdir()
        (sub / "logger.py").write_text(textwrap.dedent('''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''').strip())
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_multi_handler_in_one_try(self, tmp_path):
        """A single try with two except handlers, one silent
        and one logged -- the silent one should be flagged."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def f():
                try:
                    do_thing()
                except KeyError as exc:
                    logging.warning("k: %s", exc)
                except ValueError:
                    pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # Only the ValueError handler is silent
        assert len(report.silent_sites) == 1

    def test_scans_count_includes_skipped(self, tmp_path):
        """scanned_modules counts files even when their handlers
        are clean -- useful as a denominator for ratios."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "clean.py", '''
            def f():
                return 1
        ''')
        _write(tmp_path, "dirty.py", '''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.scanned_modules == 2
        assert len(report.silent_sites) == 1

    def test_no_pass_with_other_statement_not_flagged(
        self, tmp_path,
    ):
        """except body with assignment + pass is NOT just-pass."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f():
                try:
                    do_thing()
                except Exception:
                    x = 1
                    pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False
