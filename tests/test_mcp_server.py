"""Tests for mcp_server.server — stdio JSON-RPC transport (A5)."""
from __future__ import annotations

import io
import json
import unittest

from mcp_server.server import StdioServer, _parse_request
from mcp_server.tools import (
    ToolRegistry,
    ToolSpec,
    build_default_registry,
)


def _tiny_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="echo",
        description="echo args back",
        input_schema={"type": "object"},
        handler=lambda args: {"echoed": args},
    ))
    reg.register(ToolSpec(
        name="boom",
        description="always raises",
        input_schema={"type": "object"},
        handler=lambda args: (_ for _ in ()).throw(
            RuntimeError("boom"),
        ),
    ))
    return reg


def _send(server: StdioServer, method: str, *,
          rid: int = 1, params=None) -> dict:
    msg = {
        "jsonrpc": "2.0",
        "id": rid,
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return server.handle_message(
        json.dumps(msg),
    )  # type: ignore[return-value]


class TestParse(unittest.TestCase):
    def test_blank_line_returns_none(self):
        self.assertIsNone(_parse_request(""))
        self.assertIsNone(_parse_request("   "))

    def test_notification_returns_none(self):
        self.assertIsNone(_parse_request(
            '{"jsonrpc":"2.0","method":"x"}',
        ))

    def test_invalid_json_raises(self):
        from mcp_server.server import ProtocolError
        with self.assertRaises(ProtocolError):
            _parse_request("not json")

    def test_missing_method_raises(self):
        from mcp_server.server import ProtocolError
        with self.assertRaises(ProtocolError):
            _parse_request(
                '{"jsonrpc":"2.0","id":1}',
            )

    def test_good_request_parses(self):
        req = _parse_request(
            '{"jsonrpc":"2.0","id":7,"method":"ping"}',
        )
        self.assertIsNotNone(req)
        self.assertEqual(req.id, 7)
        self.assertEqual(req.method, "ping")


class TestInitialize(unittest.TestCase):
    def test_initialize_returns_server_info(self):
        server = StdioServer(_tiny_registry())
        resp = _send(server, "initialize")
        self.assertEqual(resp["id"], 1)
        self.assertEqual(
            resp["result"]["serverInfo"]["name"], "shopai",
        )
        self.assertIn(
            "tools", resp["result"]["capabilities"],
        )

    def test_ping_returns_empty_ok(self):
        server = StdioServer(_tiny_registry())
        resp = _send(server, "ping", rid=9)
        self.assertEqual(resp["id"], 9)
        self.assertEqual(resp["result"], {})


class TestToolsList(unittest.TestCase):
    def test_lists_registered_tools(self):
        server = StdioServer(_tiny_registry())
        resp = _send(server, "tools/list")
        names = {
            t["name"] for t in resp["result"]["tools"]
        }
        self.assertEqual(names, {"echo", "boom"})

    def test_default_registry_has_core_tools(self):
        server = StdioServer(build_default_registry())
        resp = _send(server, "tools/list")
        names = {
            t["name"] for t in resp["result"]["tools"]
        }
        for expected in (
            "brain_snapshot", "risk_status",
            "landed_cost_calc", "launch_simulate",
            "emergency_halt",
        ):
            self.assertIn(expected, names)


class TestToolsCall(unittest.TestCase):
    def test_call_echoes_arguments(self):
        server = StdioServer(_tiny_registry())
        resp = _send(
            server, "tools/call",
            params={
                "name": "echo",
                "arguments": {"x": 1},
            },
        )
        self.assertFalse(resp["result"]["isError"])
        payload = json.loads(
            resp["result"]["content"][0]["text"],
        )
        self.assertEqual(payload["echoed"], {"x": 1})

    def test_call_missing_name(self):
        server = StdioServer(_tiny_registry())
        resp = _send(
            server, "tools/call", params={"arguments": {}},
        )
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_call_unknown_tool(self):
        server = StdioServer(_tiny_registry())
        resp = _send(
            server, "tools/call",
            params={"name": "nope"},
        )
        self.assertTrue(resp["result"]["isError"])

    def test_handler_crash_becomes_tool_error(self):
        server = StdioServer(_tiny_registry())
        resp = _send(
            server, "tools/call",
            params={"name": "boom"},
        )
        self.assertTrue(resp["result"]["isError"])
        self.assertIn(
            "boom", resp["result"]["content"][0]["text"],
        )


class TestUnknownMethod(unittest.TestCase):
    def test_method_not_found(self):
        server = StdioServer(_tiny_registry())
        resp = _send(server, "resources/list")
        self.assertEqual(resp["error"]["code"], -32601)


class TestProtocolError(unittest.TestCase):
    def test_bad_json_returns_parse_error(self):
        server = StdioServer(_tiny_registry())
        resp = server.handle_message("not json")
        self.assertEqual(resp["error"]["code"], -32700)


class TestServeLoop(unittest.TestCase):
    def test_end_to_end_over_string_io(self):
        lines = [
            json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method": "initialize",
            }),
            json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "method": "tools/list",
            }),
            json.dumps({
                "jsonrpc": "2.0", "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {"hi": True},
                },
            }),
        ]
        stdin = io.StringIO("\n".join(lines) + "\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        server = StdioServer(
            _tiny_registry(),
            stdin=stdin, stdout=stdout, stderr=stderr,
        )
        server.serve_forever()
        out_lines = [
            line for line in stdout.getvalue().splitlines()
            if line.strip()
        ]
        self.assertEqual(len(out_lines), 3)
        r1 = json.loads(out_lines[0])
        r2 = json.loads(out_lines[1])
        r3 = json.loads(out_lines[2])
        self.assertEqual(r1["id"], 1)
        self.assertIn("serverInfo", r1["result"])
        self.assertEqual(r2["id"], 2)
        self.assertTrue(
            any(
                t["name"] == "echo"
                for t in r2["result"]["tools"]
            ),
        )
        self.assertEqual(r3["id"], 3)
        self.assertFalse(r3["result"]["isError"])

    def test_blank_lines_do_not_produce_output(self):
        stdin = io.StringIO("\n\n\n")
        stdout = io.StringIO()
        server = StdioServer(
            _tiny_registry(),
            stdin=stdin, stdout=stdout,
            stderr=io.StringIO(),
        )
        server.serve_forever()
        self.assertEqual(
            stdout.getvalue().strip(), "",
        )


if __name__ == "__main__":
    unittest.main()
