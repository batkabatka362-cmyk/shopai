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


class TestNestedRollbackSkipped:
    """Refinement: an inner ``except: pass`` whose OUTER handler
    has a logger call is the canonical 'rollback after a logged
    failure' pattern and not a violation. The outer log already
    carries the diagnostic signal."""

    def test_inner_rollback_after_logged_outer_skipped(
        self, tmp_path,
    ):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def f(conn):
                try:
                    conn.execute("INSERT ...")
                    conn.commit()
                except RuntimeError as exc:
                    logging.warning("insert failed: %s", exc)
                    try:
                        conn.rollback()
                    except RuntimeError:
                        pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # Inner pass is suppressed; outer logged so the
        # nested-rollback pattern is recognised as fine.
        assert report.has_violations is False

    def test_inner_pass_without_outer_log_still_flagged(
        self, tmp_path,
    ):
        """If the OUTER except also doesn't log, the inner
        ``except: pass`` IS a violation (the outer is too, but
        we report each handler separately)."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f(conn):
                try:
                    conn.execute("INSERT ...")
                except RuntimeError:
                    try:
                        conn.rollback()
                    except RuntimeError:
                        pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # The inner ``except: pass`` is the only just-pass
        # handler. Outer doesn't log -> inner is flagged.
        assert len(report.silent_sites) == 1

    def test_outer_log_via_unknown_method_does_not_count(
        self, tmp_path,
    ):
        """Detection looks for attribute names in the logger-
        level set. A method named ``record`` does NOT count."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            class X:
                def record(self, msg): pass
            x = X()
            def f(conn):
                try:
                    conn.execute("X")
                except RuntimeError as exc:
                    x.record(str(exc))
                    try:
                        conn.rollback()
                    except RuntimeError:
                        pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert len(report.silent_sites) == 1

    def test_any_log_level_qualifies(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        for level in (
            "debug", "info", "warning", "error", "critical",
        ):
            _write(tmp_path, f"{level}_mod.py", f'''
                import logging
                def f(conn):
                    try:
                        conn.execute("X")
                    except RuntimeError as exc:
                        logging.{level}("oops: %s", exc)
                        try:
                            conn.rollback()
                        except RuntimeError:
                            pass
            ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False


class TestFallThroughChainSkipped:
    """Refinement: an ``except: pass`` followed by ANOTHER try
    statement (parse-chain), a logger call (parse-then-log), or
    a return (parse-then-return-default) is intentional control
    flow and not a silent swallow."""

    def test_followed_by_another_try_skipped(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def parse(s):
                try:
                    return float(s)
                except ValueError:
                    pass
                try:
                    return parse_iso(s)
                except ValueError:
                    return None
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # First handler is followed by another try -> skipped.
        # Second handler isn't a just-pass.
        assert report.has_violations is False

    def test_followed_by_logger_call_skipped(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def parse(s):
                try:
                    return datetime.fromisoformat(s)
                except ValueError:
                    pass
                logging.warning("could not parse '%s'", s)
                return s
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # except: pass followed by logger.warning -> skipped.
        assert report.has_violations is False

    def test_followed_by_return_skipped(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def parse(s):
                try:
                    return float(s)
                except ValueError:
                    pass
                return 0.0
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # except: pass followed by return -> the return IS the
        # signal (default value).
        assert report.has_violations is False

    def test_followed_by_assignment_still_flagged(
        self, tmp_path,
    ):
        """An assignment is NOT a recognised end-of-chain marker
        (could be hiding a real bug like ``x = some_default``
        with no diagnostic). Stays a violation."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f(x):
                try:
                    do_thing(x)
                except Exception:
                    pass
                x = 1
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert len(report.silent_sites) == 1

    def test_followed_by_nothing_still_flagged(self, tmp_path):
        """``except: pass`` at the end of a block with no
        following statement is the classic silent swallow."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f():
                try:
                    do_thing()
                except Exception:
                    pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert len(report.silent_sites) == 1

    def test_continue_then_pass_in_loop_still_flagged(
        self, tmp_path,
    ):
        """Inside a for-loop body, ``except: pass`` followed by
        the next iteration is NOT a fall-through chain -- the
        next ""statement"" is the continue from loop iteration,
        not a sibling statement in the same block."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f(items):
                for x in items:
                    try:
                        do_thing(x)
                    except Exception:
                        pass
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # The except is the last statement in the for-body, so
        # there's no next sibling -> still flagged.
        assert len(report.silent_sites) == 1

    def test_followed_by_logger_attribute_chain(self, tmp_path):
        """Logger calls via ``logger.warning(...)`` style with
        a bound module attribute -- the detector should match
        on the .warning method name."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            from utils.logger import get_logger
            logger = get_logger("mod")
            def parse(s):
                try:
                    return _strict_parse(s)
                except ValueError:
                    pass
                logger.warning("falling back for %s", s)
                return s
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_followed_by_log_via_func_call_not_skipped(
        self, tmp_path,
    ):
        """A bare function call like ``record(s)`` is NOT
        recognised as a log -- only attribute-method calls
        with the standard logger-level names qualify."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def record(s): pass
            def parse(s):
                try:
                    return _strict_parse(s)
                except ValueError:
                    pass
                record(s)
                return s
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        # record(s) isn't a logger.<level>(...) call, so the
        # except: pass is still flagged (return after the
        # record IS a return-default, though). Wait -- the
        # IMMEDIATELY next statement after the try is
        # record(s), which isn't a logger call. So the
        # fall-through rule doesn't apply. The handler IS
        # flagged.
        assert len(report.silent_sites) == 1


class TestIfBodyFallThroughSkipped:
    """Refinement #3: when the try is the LAST statement in an
    ``if`` body (no else), falling out of the if naturally
    continues to the next sibling at the parent level.
    """

    def test_try_in_if_body_then_log_after_if(self, tmp_path):
        """Canonical case: try in if-body, after the if there's
        a log call. Falling through the if reaches the log."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def parse(s):
                if s:
                    try:
                        return _strict_parse(s)
                    except (ValueError, TypeError):
                        pass
                logging.warning("could not parse %s", s)
                return None
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_try_in_if_body_then_return_after_if(self, tmp_path):
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def parse(s):
                if s:
                    try:
                        return float(s)
                    except ValueError:
                        pass
                return 0.0
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_try_in_nested_if_bodies(self, tmp_path):
        """Walk up TWO levels: try in inner-if-body, inner-if
        is last in outer-if-body, outer-if followed by log."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def parse(s):
                if s is not None:
                    if isinstance(s, str):
                        try:
                            return float(s)
                        except ValueError:
                            pass
                logging.warning("could not parse %s", s)
                return None
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert report.has_violations is False

    def test_try_in_for_body_does_NOT_fall_through(
        self, tmp_path,
    ):
        """For-loop body fall-through is next-iteration, not
        post-loop. Audit conservatively keeps these flagged."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def f(items):
                for x in items:
                    try:
                        do_thing(x)
                    except Exception:
                        pass
                logging.warning("loop finished")
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert len(report.silent_sites) == 1

    def test_try_in_else_body_does_NOT_fall_through(
        self, tmp_path,
    ):
        """Conservative: only ``body`` branch qualifies; the
        else-body's fall-through depends on which branch
        executed. Stays flagged."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            import logging
            def f():
                if cond():
                    do_it()
                else:
                    try:
                        do_other()
                    except Exception:
                        pass
                logging.warning("done")
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert len(report.silent_sites) == 1

    def test_try_in_if_with_non_marker_sibling(
        self, tmp_path,
    ):
        """Try in if-body, after the if is a non-marker stmt
        (like a function call) -- not skipped, still flagged."""
        from engines._pattern_s_audit import audit_pattern_s
        _write(tmp_path, "mod.py", '''
            def f(x):
                if cond(x):
                    try:
                        do_it(x)
                    except Exception:
                        pass
                process(x)
        ''')
        report = audit_pattern_s(roots=[tmp_path])
        assert len(report.silent_sites) == 1
