"""AgentManager facade wire-in tests (quality audit item #10).

Pre-audit: AgentManager existed but wasn't reachable through
``interface/`` or ``shopai`` CLI or MCP — callers had to
reach into ``agents.manager``. This test locks in the
reconnection:
  1. get_agent_manager() returns a process-wide singleton
  2. interface/__init__.py re-exports AgentManager +
     get_agent_manager
  3. CLI + MCP tool both return the same agent records
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from agents.manager import (
    AgentManager,
    get_agent_manager,
    reset_agent_manager_for_tests,
)


class TestSingleton(unittest.TestCase):
    def setUp(self):
        reset_agent_manager_for_tests()

    def tearDown(self):
        reset_agent_manager_for_tests()

    def test_returns_same_instance(self):
        a = get_agent_manager()
        b = get_agent_manager()
        self.assertIs(a, b)

    def test_reset_produces_fresh_instance(self):
        a = get_agent_manager()
        reset_agent_manager_for_tests()
        b = get_agent_manager()
        self.assertIsNot(a, b)


class TestInterfaceFacade(unittest.TestCase):
    def test_re_exports_both_symbols(self):
        import interface
        self.assertIs(
            interface.AgentManager, AgentManager,
        )
        self.assertIs(
            interface.get_agent_manager,
            get_agent_manager,
        )

    def test_symbols_in_all(self):
        import interface
        self.assertIn("AgentManager", interface.__all__)
        self.assertIn(
            "get_agent_manager", interface.__all__,
        )


class TestCliAgentsCommand(unittest.TestCase):
    def setUp(self):
        reset_agent_manager_for_tests()
        mgr = get_agent_manager()
        mgr.register_agent(
            "content-1", "content",
            {"role": "copywriter"},
        )
        mgr.register_agent(
            "finance-1", "finance",
            {"role": "budget-watch"},
        )

    def tearDown(self):
        reset_agent_manager_for_tests()

    def test_list_table_all(self):
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_agents_list(
                type_filter=None, as_json=False,
            )
        out = buf.getvalue()
        self.assertIn("Registered agents", out)
        self.assertIn("content-1", out)
        self.assertIn("finance-1", out)

    def test_list_filtered_by_type(self):
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_agents_list(
                type_filter="finance", as_json=False,
            )
        out = buf.getvalue()
        self.assertIn("finance-1", out)
        self.assertNotIn("content-1", out)

    def test_list_json(self):
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_agents_list(
                type_filter=None, as_json=True,
            )
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["count"], 2)
        ids = [a["id"] for a in payload["agents"]]
        self.assertIn("content-1", ids)
        self.assertIn("finance-1", ids)

    def test_list_empty_shows_hint(self):
        reset_agent_manager_for_tests()
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_agents_list(
                type_filter=None, as_json=False,
            )
        self.assertIn(
            "register via",
            buf.getvalue().lower(),
        )

    def test_get_shows_record(self):
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_agents_get(
                agent_id="content-1", as_json=False,
            )
        self.assertIn("content-1", buf.getvalue())

    def test_get_unknown_exits_nonzero(self):
        import cli
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(buf):
                cli._cmd_agents_get(
                    agent_id="ghost", as_json=False,
                )
        self.assertEqual(ctx.exception.code, 1)


class TestMcpTool(unittest.TestCase):
    def setUp(self):
        reset_agent_manager_for_tests()

    def tearDown(self):
        reset_agent_manager_for_tests()

    def test_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("agents_list", names)

    def test_returns_registered_agents(self):
        mgr = get_agent_manager()
        mgr.register_agent(
            "research-1", "research",
            {"role": "niche-discovery"},
        )
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        reg = build_default_registry()
        res = reg.call(ToolCall(tool="agents_list"))
        self.assertTrue(res.ok)
        self.assertEqual(res.content["count"], 1)
        self.assertEqual(
            res.content["agents"][0]["id"], "research-1",
        )

    def test_type_filter(self):
        mgr = get_agent_manager()
        mgr.register_agent(
            "a", "content", {},
        )
        mgr.register_agent(
            "b", "finance", {},
        )
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="agents_list",
            arguments={"type": "finance"},
        ))
        self.assertEqual(res.content["count"], 1)
        self.assertEqual(
            res.content["type_filter"], "finance",
        )


if __name__ == "__main__":
    unittest.main()
