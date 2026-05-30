"""Tests for autonomy_overview render functions (Wave 897-898)."""
from __future__ import annotations

from core.automation.autonomy_overview import (
    OverviewSnapshot,
    render_markdown,
    render_shell_prompt,
    render_text,
)


def _snap(**kw):
    s = OverviewSnapshot()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class TestRenderText:

    def test_idle(self):
        out = render_text(_snap())
        assert "verdict=idle" in out
        assert "armed=0" in out
        assert "fleet" in out

    def test_per_store(self):
        out = render_text(_snap(store_id="store-7"))
        assert "store=store-7" in out

    def test_active_carries_fire_ratio(self):
        s = _snap(
            armed_total=3, fires_total=10, fires_invoked=7,
        )
        assert "fires=7/10" in render_text(s)


class TestRenderMarkdown:

    def test_header_with_window(self):
        out = render_markdown(_snap(window_hours=72))
        assert "### Autonomy overview" in out
        assert "72h" in out

    def test_table_shape(self):
        out = render_markdown(_snap())
        lines = out.splitlines()
        assert any("|---" in line for line in lines)
        assert any("**idle**" in line for line in lines)

    def test_per_store_in_backticks(self):
        out = render_markdown(_snap(store_id="store-7"))
        assert "`store-7`" in out

    def test_degraded_emphasized(self):
        s = _snap(alerts_critical=1, armed_total=2)
        out = render_markdown(s)
        assert "**degraded**" in out


class TestRenderShellPrompt:

    def test_idle_marker(self):
        out = render_shell_prompt(_snap())
        assert out.startswith("[.]")
        assert "idl" in out
        assert " a0" in out

    def test_armed_marker(self):
        s = _snap(armed_total=2)
        assert render_shell_prompt(s).startswith("[~]")

    def test_active_marker(self):
        s = _snap(armed_total=2, fires_invoked=5,
                  fires_total=5)
        assert render_shell_prompt(s).startswith("[>]")

    def test_degraded_marker(self):
        s = _snap(armed_total=1, alerts_critical=1)
        out = render_shell_prompt(s)
        assert out.startswith("[!]")
        assert "!1" in out

    def test_no_trailing_newline(self):
        out = render_shell_prompt(_snap())
        assert not out.endswith("\n")

    def test_compact_form(self):
        # PS1 embedding needs a short token
        out = render_shell_prompt(_snap(
            armed_total=10, fires_total=99, fires_invoked=50,
            fires_errors=3, alerts_critical=2,
        ))
        # All fields visible; tokens separated by spaces
        assert "a10" in out
        assert "f50/99" in out
        assert "e3" in out
        assert "!2" in out
