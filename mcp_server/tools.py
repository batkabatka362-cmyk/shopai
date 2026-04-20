"""ShopAI MCP tool registry.

Wave B-2 of IMPLEMENTATION_PLAN_2026. Exposes the ShopAI brain
as Model Context Protocol tools so Claude Desktop / Claude Code
/ Cursor / any MCP-compatible client can drive the store.

This module is intentionally *transport-agnostic* — it defines
the tool contracts, JSON schemas, and handlers, but does NOT
own the stdio/websocket wire format. The thin wire layer in
``mcp_server/server.py`` (Python MCP SDK) imports this registry
and routes calls in.

Exposed tools (v1):

  * ``brain_snapshot``       — holistic BrainState dict
  * ``risk_status``          — tripwire + crisis summary
  * ``list_rules``           — RuleBook top-N by confidence
  * ``explain_decision``     — replay rationale for decision_id
  * ``agentic_channels``     — per-AI-channel enrollment + GMV
  * ``landed_cost_calc``     — pure-function COGS calculator
  * ``top_niches``           — ranked niche list (if discovered)
  * ``launch_simulate``      — Monte Carlo projection for a
                               candidate product
  * ``emergency_halt``       — owner-triggered kill switch
  * ``emergency_resume``     — clear manual halt

Tools are:
  * Deterministic where possible (landed_cost_calc, explain)
  * Read-heavy (snapshot / status / channels)
  * Write-guarded — emergency_halt is the only write; callers
    must confirm intent

Pure stdlib. Tests inject MagicMock backends so the registry
runs offline. JSON schemas intentionally minimal — MCP clients
can call in with partial fields.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolCall:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "request_id": self.request_id,
        }


@dataclass
class ToolResult:
    tool: str
    ok: bool
    content: Any = None
    error: str = ""
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "content": self.content,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 2),
        }

    def to_mcp(self) -> dict[str, Any]:
        """Shape MCP protocol expects on a CallToolResult."""
        if self.ok:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            json.dumps(
                                self.content, indent=2,
                            )
                            if not isinstance(
                                self.content, str,
                            )
                            else self.content
                        ),
                    },
                ],
                "isError": False,
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: {self.error}",
                },
            ],
            "isError": True,
        }


class ToolError(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    write: bool = False  # true → side-effect

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "write": self.write,
        }


class ToolRegistry:
    """Thread-safe tool name → handler map."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tools: dict[str, ToolSpec] = {}
        self._calls = 0
        self._errors = 0

    def register(self, spec: ToolSpec) -> None:
        if not spec.name:
            raise ValueError("tool name required")
        with self._lock:
            if spec.name in self._tools:
                raise ValueError(
                    f"duplicate tool {spec.name!r}",
                )
            self._tools[spec.name] = spec

    def list_tools(self) -> list[ToolSpec]:
        with self._lock:
            return list(self._tools.values())

    def call(self, call: ToolCall) -> ToolResult:
        if not isinstance(call, ToolCall):
            raise TypeError("call must be ToolCall")
        with self._lock:
            spec = self._tools.get(call.tool)
        if spec is None:
            return ToolResult(
                tool=call.tool,
                ok=False,
                error=f"unknown tool {call.tool!r}",
            )
        t0 = time.time()
        try:
            content = spec.handler(call.arguments or {})
            dt = (time.time() - t0) * 1000
            with self._lock:
                self._calls += 1
            return ToolResult(
                tool=call.tool,
                ok=True,
                content=content,
                latency_ms=dt,
            )
        except ToolError as exc:
            with self._lock:
                self._calls += 1
                self._errors += 1
            return ToolResult(
                tool=call.tool,
                ok=False,
                error=str(exc),
                latency_ms=(time.time() - t0) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._calls += 1
                self._errors += 1
            return ToolResult(
                tool=call.tool,
                ok=False,
                error=f"handler crashed: {exc}",
                latency_ms=(time.time() - t0) * 1000,
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tools": sorted(self._tools.keys()),
                "total_calls": self._calls,
                "total_errors": self._errors,
            }


# ── Default handlers ───────────────────────────────────────


def _brain_snapshot_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from core.brain.brain_state_synthesizer import (
        get_brain_state_synthesizer,
    )
    synth = get_brain_state_synthesizer()
    return synth.snapshot().as_dict()


def _risk_status_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from core.risk.tripwire import get_risk_tripwire
    from core.crisis.response import (
        get_crisis_responder,
    )
    risk = get_risk_tripwire().status()
    crisis = get_crisis_responder().detect_state()
    return {"risk": risk, "crisis": crisis.as_dict()}


def _list_rules_handler(
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    from core.learning.rulebook import get_rulebook
    limit = int(args.get("limit", 10))
    book = get_rulebook()
    return [r.as_dict() for r in book.top_by_confidence(
        limit=limit,
    )]


def _explain_decision_handler(
    args: dict[str, Any],
) -> str:
    decision_id = str(args.get("decision_id", ""))
    if not decision_id:
        raise ToolError("decision_id required")
    from core.decision.rationale_ledger import (
        get_rationale_ledger,
    )
    return get_rationale_ledger().explain(decision_id)


def _agentic_channels_handler(
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    from core.bridge.agentic_storefront import (
        get_agentic_bridge,
    )
    statuses = get_agentic_bridge().status()
    return [s.as_dict() for s in statuses]


def _landed_cost_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from execution.fulfillment.landed_cost import (
        LandedCostInput,
        calculate_landed_cost,
    )
    try:
        inp = LandedCostInput(
            fob_usd=float(args.get("fob_usd", 0)),
            destination=str(args.get("destination", "US")),
            origin=str(args.get("origin", "CN")),
            hts_code=str(args.get("hts_code", "")),
            shipping_usd=float(
                args.get("shipping_usd", 0),
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid args: {exc}") from exc
    r = calculate_landed_cost(inp)
    return r.as_dict()


def _emergency_halt_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    reason = str(args.get("reason", "owner via mcp"))
    from core.crisis.response import (
        get_crisis_responder,
    )
    get_crisis_responder().halt(reason=reason)
    return {
        "halted": True,
        "reason": reason,
    }


def _emergency_resume_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from core.crisis.response import (
        get_crisis_responder,
    )
    cr = get_crisis_responder()
    cr.resume()
    state = cr.detect_state()
    return {
        "halted": state.halted,
        "reason": state.reason,
    }


def _moby_win_rate_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from core.brain.moby_vote_comparator import (
        get_moby_vote_comparator,
    )
    return get_moby_vote_comparator().win_rate()


def _fal_budget_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from core.adapters.fal.video_router import (
        FalVideoRouter,
    )
    router = FalVideoRouter()
    try:
        stats = router.stats()
        sku = str(args.get("sku", ""))
        if sku:
            stats["sku_spent_this_week_usd"] = (
                router.spent_this_week(sku)
            )
            stats["sku"] = sku
        return stats
    finally:
        router.close()


def _oauth_status_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    from core.auth.token_resolver import (
        _get_auth, has_oauth_config, source_for,
    )
    import os as _os
    shop = str(
        args.get("shop")
        or _os.environ.get("SHOPAI_SHOPIFY_URL", ""),
    )
    payload: dict[str, Any] = {
        "shop": shop,
        "oauth_configured": has_oauth_config(),
        "source": source_for(shop),
    }
    if has_oauth_config() and shop:
        auth = _get_auth()
        if auth is not None:
            try:
                payload["token_status"] = (
                    auth.token_status(shop)
                )
            except Exception as exc:  # noqa: BLE001
                payload["token_status_error"] = str(exc)
    return payload


def _launch_simulate_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    try:
        from simulation.launch_simulator import (
            LaunchCandidate,
            simulate_launch,
        )
        cand = LaunchCandidate(
            cost=float(args.get("cost", 0)),
            price=float(args.get("price", 0)),
            daily_budget_usd=float(
                args.get("daily_budget_usd", 0),
            ),
            days=int(args.get("days", 3)),
        )
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid args: {exc}") from exc
    proj = simulate_launch(cand)
    return proj.as_dict()


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="brain_snapshot",
        description=(
            "Return the current ShopAI BrainState — crisis, "
            "tripwire, memory, trust, learned rules, derived "
            "priorities."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_brain_snapshot_handler,
    ))
    reg.register(ToolSpec(
        name="risk_status",
        description=(
            "Risk tripwire today + crisis responder level."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_risk_status_handler,
    ))
    reg.register(ToolSpec(
        name="list_rules",
        description=(
            "Top learned rules by confidence — what ShopAI's "
            "brain has concluded from outcomes."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                },
            },
        },
        handler=_list_rules_handler,
    ))
    reg.register(ToolSpec(
        name="explain_decision",
        description=(
            "Replay the rationale tree for a past decision."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "decision_id": {"type": "string"},
            },
            "required": ["decision_id"],
        },
        handler=_explain_decision_handler,
    ))
    reg.register(ToolSpec(
        name="agentic_channels",
        description=(
            "ChatGPT / Perplexity / Copilot / Gemini "
            "enrollment + attributed orders."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_agentic_channels_handler,
    ))
    reg.register(ToolSpec(
        name="landed_cost_calc",
        description=(
            "Pure-function landed-cost calculation including "
            "de-minimis awareness."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "fob_usd": {"type": "number"},
                "destination": {
                    "type": "string",
                    "enum": ["US", "EU", "UK"],
                },
                "origin": {"type": "string"},
                "hts_code": {"type": "string"},
                "shipping_usd": {"type": "number"},
            },
            "required": ["fob_usd", "destination"],
        },
        handler=_landed_cost_handler,
    ))
    reg.register(ToolSpec(
        name="launch_simulate",
        description=(
            "Monte Carlo profit projection for a product "
            "launch candidate."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cost": {"type": "number"},
                "price": {"type": "number"},
                "daily_budget_usd": {"type": "number"},
                "days": {"type": "integer"},
            },
            "required": ["cost", "price", "daily_budget_usd"],
        },
        handler=_launch_simulate_handler,
    ))
    reg.register(ToolSpec(
        name="moby_win_rate",
        description=(
            "Triple Whale Moby vs ShopAI vote-comparator "
            "summary over resolved campaign disagreements."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_moby_win_rate_handler,
    ))
    reg.register(ToolSpec(
        name="fal_budget_status",
        description=(
            "fal.ai video router budget — weekly cap, "
            "total spend, optional per-SKU spend."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sku": {
                    "type": "string",
                    "description": (
                        "Optional SKU to add per-SKU "
                        "weekly spend"
                    ),
                },
            },
        },
        handler=_fal_budget_handler,
    ))
    reg.register(ToolSpec(
        name="oauth_status",
        description=(
            "Shopify OAuth token source + expiry + "
            "refresh health for the target shop."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "shop": {
                    "type": "string",
                    "description": (
                        "Shop domain; defaults to "
                        "SHOPAI_SHOPIFY_URL env"
                    ),
                },
            },
        },
        handler=_oauth_status_handler,
    ))
    reg.register(ToolSpec(
        name="emergency_halt",
        description=(
            "Engage the crisis kill switch (stops every "
            "live write). Owner-gated."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
            },
        },
        handler=_emergency_halt_handler,
        write=True,
    ))
    reg.register(ToolSpec(
        name="emergency_resume",
        description=(
            "Clear manual halt. Events may keep the system "
            "halted."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_emergency_resume_handler,
        write=True,
    ))
    return reg
