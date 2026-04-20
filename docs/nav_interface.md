# nav: interface

Every surface the owner talks to.

## Physical source

- `cli.py` — ~3800 lines. Command-driven entry. Run
  `python cli.py --help`.
- `api/server.py` — HTTP API (port 8080).
- `mcp_server/` — Model Context Protocol server.
  - `tools.py` — 9 registered tools.
  - `server.py` — stdio JSON-RPC transport (A5).
- `agents/owner_dialog/` — natural-language owner dialog
  agent.
- `dashboard.py` — terminal dashboard (`--live` for watch
  mode; HTTP UI on 8082).

## Facade

`interface/__init__.py` re-exports `ToolRegistry`,
`StdioServer`, `build_default_registry`, dashboard helpers.

## MCP tool catalogue

```
brain_snapshot      risk_status         list_rules
explain_decision    agentic_channels    landed_cost_calc
launch_simulate     emergency_halt      emergency_resume
```

Wire a new tool: register a ToolSpec in
`mcp_server/tools.py::build_default_registry` with a
handler + minimal JSON schema. Register writes with
`write=True` so the host can prompt.

## Claude Desktop config

```json
{
  "mcpServers": {
    "shopai": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {"PYTHONPATH": "/path/to/shopai"}
    }
  }
}
```

## When to edit

- New CLI command → `cli.py`. If it needs a daemon,
  route via `scripts/`.
- New HTTP route → `api/server.py`. Use
  `core/bridge/shopify_connector.py` for any Shopify I/O.
- New owner question → add to
  `agents/owner_dialog/planner.py`.
