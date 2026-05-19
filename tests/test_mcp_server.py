"""Tests for ``core.mcp_server.server``.

The MCP server machinery requires the optional ``mcp``
package. These tests verify:

  1. ``build_server()`` raises a friendly RuntimeError
     when the package isn't installed.
  2. The module imports cleanly without ``mcp`` -- the
     lazy import lives inside ``build_server()`` not
     at module top.
  3. ``main()`` handles the missing-package error
     gracefully with a non-zero exit + stderr message.
"""
from __future__ import annotations

import builtins
import sys

import pytest


def test_module_imports_without_mcp():
    """The server module must import cleanly even when
    the ``mcp`` package is missing. The lazy import keeps
    the autonomous-engine path deployable in environments
    that don't want the MCP dependency."""
    import core.mcp_server.server as server_mod
    assert hasattr(server_mod, "build_server")
    assert hasattr(server_mod, "main")


def test_build_server_raises_without_mcp(monkeypatch):
    """When the ``mcp`` package is unavailable,
    ``build_server()`` must raise a friendly RuntimeError
    with the install hint -- not a raw ImportError."""
    # If mcp is installed in the test env, skip -- we
    # can't test the missing-package path without
    # rigging the import system.
    try:
        import mcp  # noqa: F401
        pytest.skip(
            "mcp package is installed; can't test "
            "missing-package path",
        )
    except ImportError:
        pass

    from core.mcp_server.server import build_server
    with pytest.raises(RuntimeError) as exc_info:
        build_server()
    msg = str(exc_info.value)
    assert "mcp" in msg.lower()
    assert "install" in msg.lower()


def test_main_exits_cleanly_when_mcp_missing(
    monkeypatch, capsys,
):
    """``main()`` should sys.exit(2) with a stderr message
    when ``mcp`` is missing, not crash with a stacktrace."""
    try:
        import mcp  # noqa: F401
        pytest.skip(
            "mcp package is installed",
        )
    except ImportError:
        pass

    from core.mcp_server.server import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    # Operator-actionable error in stderr
    assert (
        "ShopAI MCP server failed to start"
        in captured.err
    )
    assert "mcp" in captured.err.lower()


def test_module_constants():
    """Server name + version are stable -- changing them
    requires deliberate consideration since Claude
    Desktop pins the server identity."""
    import core.mcp_server.server as server_mod
    assert server_mod._SERVER_NAME == "shopai"
    # Version is semver-like
    parts = server_mod._SERVER_VERSION.split(".")
    assert len(parts) == 3
    for p in parts:
        assert p.isdigit(), parts
