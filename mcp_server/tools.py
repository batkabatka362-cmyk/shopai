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
import logging
import threading

_logger = logging.getLogger(__name__)

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
    # Telemetry — mirrors ``core.adapters.base.AdapterResult``
    # so an MCP tool that wraps an adapter call can preserve
    # the vendor's cost + token accounting instead of losing
    # it at the boundary. Defaults are zeros so existing
    # in-process handlers (no external call) keep their
    # previous payload shape.
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    adapter: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "content": self.content,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 2),
            "cost_usd": round(self.cost_usd, 6),
            "tokens_in": int(self.tokens_in),
            "tokens_out": int(self.tokens_out),
            "model": self.model,
            "adapter": self.adapter,
        }

    @classmethod
    def from_adapter_result(
        cls,
        tool: str,
        adapter_result: Any,
    ) -> "ToolResult":
        """Factory that copies the telemetry + ok/error
        shape from a ``core.adapters.base.AdapterResult`` so
        MCP tools that wrap adapter calls preserve vendor
        cost accounting end-to-end.
        """
        ok = bool(getattr(adapter_result, "ok", False))
        content = getattr(adapter_result, "data", None)
        error_obj = getattr(adapter_result, "error", None)
        # AdapterResult.error is an AdapterError dataclass;
        # stringify when present.
        err_text = str(error_obj) if error_obj else ""
        return cls(
            tool=tool,
            ok=ok,
            content=content,
            error=err_text,
            latency_ms=float(
                getattr(adapter_result, "latency_ms", 0.0)
                or 0.0,
            ),
            cost_usd=float(
                getattr(adapter_result, "cost_usd", 0.0)
                or 0.0,
            ),
            tokens_in=int(
                getattr(adapter_result, "tokens_in", 0)
                or 0,
            ),
            tokens_out=int(
                getattr(adapter_result, "tokens_out", 0)
                or 0,
            ),
            model=str(
                getattr(adapter_result, "model", "")
                or "",
            ),
            adapter=str(
                getattr(adapter_result, "adapter", "")
                or "",
            ),
        )

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


def _trust_status_handler(
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Source-trust calibrator ranking — which data sources
    ShopAI weights heaviest. Owner uses this to decide which
    source to trust when two disagree."""
    from core.data.source_trust_calibrator import (
        get_calibrator,
    )
    c = get_calibrator()
    out: list[dict[str, Any]] = []
    for name, trust in c.ranked():
        stats = c.get(name)
        out.append({
            "source": name,
            "trust": round(float(trust), 4),
            "samples": int(stats.samples),
            "win_ema": round(float(stats.win_ema), 4),
            "error_rate_ema": round(
                float(stats.error_rate_ema), 4,
            ),
        })
    return out


def _memory_ladder_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Episode → concept → procedure memory ladder counts
    plus the promotion thresholds.  Owner uses this to
    understand what ShopAI is learning long-term."""
    from core.memory.consolidator import get_consolidator
    return get_consolidator().stats()


def _recent_decisions_handler(
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Recent decisions with their rationale summaries.
    Pair with the existing ``explain_decision`` tool to
    drill in."""
    from core.decision.rationale_ledger import (
        get_rationale_ledger,
    )
    try:
        limit = int(args.get("limit", 20) or 20)
    except (TypeError, ValueError):
        limit = 20
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    records = get_rationale_ledger().recent(limit=limit)
    return [r.as_dict() for r in records]


def _predict_outcome_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """World-model what-if: given an action/kpi/context,
    return the bias-adjusted mean + calibrated stdev +
    confidence band ShopAI would use to decide."""
    from core.brain.world_model_calibration import (
        get_world_model_calibration,
    )
    action = str(args.get("action", "")).strip()
    kpi = str(args.get("kpi", "")).strip()
    if not action or not kpi:
        raise ToolError("action and kpi required")
    context = {
        "niche": str(args.get("niche", "") or ""),
        "price_band": str(
            args.get("price_band", "") or "",
        ),
        "margin_band": str(
            args.get("margin_band", "") or "",
        ),
        "copy_tone": str(args.get("tone", "") or ""),
    }
    pred = get_world_model_calibration().predict(
        action=action, kpi=kpi, context=context,
    )
    return pred.as_dict()


def _doctor_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Run doctor probes and return the structured report.
    Owner asks Claude Desktop "is everything connected?" and
    gets a real answer instead of a schema check."""
    from core.readiness.doctor import run as _run_doctor
    try:
        timeout = float(args.get("timeout", 8.0) or 8.0)
    except (TypeError, ValueError):
        timeout = 8.0
    include_moby = bool(args.get("include_moby", True))
    include_vault = bool(args.get("include_vault", True))
    include_tiktok = bool(args.get("include_tiktok", True))
    report = _run_doctor(
        timeout=timeout,
        include_moby=include_moby,
        include_vault=include_vault,
        include_tiktok=include_tiktok,
    )
    return report.as_dict()


def _notify_errors_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Push a cycle-error digest to Telegram (or return the
    composed text when dry_run=True)."""
    from agents.owner_dialog.cycle_error_digest import (
        send_error_digest,
    )
    try:
        hours = float(args.get("hours", 24.0) or 24.0)
    except (TypeError, ValueError):
        hours = 24.0
    log_path = str(
        args.get("log_path")
        or "data/autopilot_loop.log",
    )
    dry_run = bool(args.get("dry_run", False))
    chat_id = args.get("chat_id")
    result = send_error_digest(
        hours=hours,
        log_path=log_path,
        dry_run=dry_run,
        chat_id=chat_id if isinstance(chat_id, str) else None,
    )
    return result.as_dict()


def _recent_deliberations_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return the last N structured-decision records so the
    owner can trace how a decision was thought through (5
    pillars: outcome, directions, constraints, refines,
    awareness). Complements explain_decision which shows
    the rationale ledger; this shows the upstream decision
    process that populates it."""
    from core.brain.structured_decision import (
        recent_deliberations,
    )
    try:
        limit = int(args.get("limit", 10) or 10)
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    records = recent_deliberations(limit=limit)
    return {
        "count": len(records),
        "deliberations": [
            r.as_dict() for r in records
        ],
    }


def _agents_list_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return every agent registered with AgentManager —
    the single specialised-agent lifecycle registry. Owner
    uses this from Claude Desktop to see what agents are
    alive + filter by type (content, finance, research, …)."""
    from agents.manager import get_agent_manager
    type_filter = str(args.get("type", "") or "") or None
    records = get_agent_manager().list_agents(
        agent_type=type_filter,
    )
    return {
        "count": len(records),
        "type_filter": type_filter,
        "agents": records,
    }


def _citations_show_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return the citation list for a niche — owner uses this
    to preview the GEO sandwich content before it ships on
    the next product description."""
    from execution.seo.citation_store import (
        available_niches,
        resolve_citations_for,
    )
    niche = str(args.get("niche", "default") or "default")
    cites = resolve_citations_for({"niche": niche})
    return {
        "niche": niche,
        "available_niches": available_niches(),
        "citations": cites,
        "count": len(cites),
    }


def _webhook_rate_limit_status_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return the per-IP webhook rate-limiter stats:
    active buckets, total consumed, total rejected, configured
    rate + burst. Owner asks Claude Desktop "is anyone
    spamming our webhook?" and gets a structured answer."""
    from core.webhooks.rate_limiter import (
        get_webhook_rate_limiter,
    )
    return get_webhook_rate_limiter().stats()


def _autopilot_status_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Report whether the 24/7 autopilot daemon is running +
    what it last did. Combines pidfile liveness + the tail of
    autopilot_loop.log. Owner asks Claude Desktop "is the
    daemon alive?" and gets a structured answer."""
    import json as _json
    from pathlib import Path as _P
    from core.system.pidfile import read_status
    status = read_status("daemon")
    log_path = str(
        args.get("log_path") or "data/autopilot_loop.log",
    )
    last_cycle: dict[str, Any] | None = None
    log = _P(log_path)
    if log.exists():
        try:
            lines = log.read_text().strip().splitlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    last_cycle = _json.loads(line)
                    break
                except _json.JSONDecodeError:
                    continue
        except OSError as exc:
            raise ToolError(
                f"cannot read log: {exc}",
            ) from exc
    return {
        "daemon": status.as_dict(),
        "latest_cycle": last_cycle,
    }


def _replay_orders_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Replay a JSONL file of Shopify order payloads
    through the live webhook pipeline. Mutates learning
    state (engine_outcome_bus + Deliberation observations),
    so marked ``write=True`` — owner must confirm through
    the dispatcher."""
    from agents.replay import replay_orders_from_file
    path = str(args.get("path", "") or "")
    if not path:
        raise ToolError("path required")
    try:
        throttle = float(
            args.get("throttle_s", 0) or 0,
        )
    except (TypeError, ValueError):
        throttle = 0.0
    try:
        stats = replay_orders_from_file(
            path, throttle_s=throttle,
        )
    except FileNotFoundError as exc:
        raise ToolError(
            f"file not found: {path}",
        ) from exc
    return stats.as_dict()


def _ingest_knowledge_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Pull an external URL / file into the structured KB so
    the oracle has source-cited facts. Owner-gated — marked
    write=True because it mutates the KB."""
    from core.memory.knowledge_ingest import (
        ingest_file,
        ingest_text,
        ingest_url,
    )
    url = str(args.get("url", "") or "").strip()
    path = str(args.get("file", "") or "").strip()
    text = str(args.get("text", "") or "")
    subject = str(args.get("subject", "") or "") or None
    if url:
        return ingest_url(url, subject=subject).as_dict()
    if path:
        return ingest_file(
            path, subject=subject,
        ).as_dict()
    if text:
        return ingest_text(
            text, subject=subject,
        ).as_dict()
    raise ToolError(
        "one of url / file / text required",
    )


def _analyze_failure_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Owner asks Claude Desktop 'why did decision X fail?'
    and gets a structured root-cause read (contributing
    factors + lesson + prevention rule). Requires a
    ``failed_episode`` dict with at minimum:
        {decision_type, action, context: {...}}
    Read-only — never mutates brain state."""
    from core.learning.root_cause_analyzer import (
        get_root_cause_analyzer,
    )
    episode = args.get("failed_episode")
    if not isinstance(episode, dict):
        raise ToolError(
            "failed_episode (dict) required",
        )
    analyzer = get_root_cause_analyzer()
    try:
        return analyzer.analyze_failure(episode)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            f"RCA raised: {type(exc).__name__}: {exc}",
        ) from exc


def _ready_for_live_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Pre-T1 go-live gate: env + doctor + learning loop +
    live-health + live-execution state. Returns READY or
    BLOCKED with a per-check fix list. Read-only."""
    from core.readiness.go_live_gate import run_go_live_gate
    skip = bool(args.get("skip_learning_loop", False))
    return run_go_live_gate(
        skip_learning_loop=skip,
    ).as_dict()


def _live_health_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Rolling health digest fused from doctor probes, recent
    autopilot cycles, and per-engine feedback trends. Answers
    'is today worse than yesterday?' without log-trawling."""
    from core.readiness.health_trend import (
        compute_live_health,
    )
    try:
        cycles = int(args.get("cycles", 20) or 20)
    except (TypeError, ValueError):
        cycles = 20
    cycles = max(1, min(cycles, 1000))
    return compute_live_health(
        cycles_limit=cycles,
    ).as_dict()


def _brain_module_catalog_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return the brain module catalog — how many modules are
    active / experimental / archived / unknown. Owner uses
    this to see which brain capabilities are live vs parked."""
    from core.brain.module_catalog import catalog_summary
    return catalog_summary()


def _engine_feedback_stats_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return per-engine feedback stats (success rate, avg
    elapsed, trend, common errors). Read from the same
    FeedbackStore the engine_outcome_bus feeds on every
    activator / publisher outcome."""
    from core.learning.feedback_store import (
        get_feedback_store,
    )
    store = get_feedback_store()
    engine = str(args.get("engine") or "").strip()
    if engine:
        return {"engine": engine, **store.get_stats(engine)}
    return {
        "engines": store.get_all_stats(),
        "persist_errors": store.get_persist_errors(),
    }


def _improvements_summary_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return summary of learning-engine improvement
    proposals + applied count + by-type distribution. Owner
    reads this to see what the system wants to change next."""
    from core.learning.improvement_tracker import (
        ImprovementTracker,
    )
    # ImprovementTracker has no singleton by design — it's
    # per-learning-source. Instantiate one on the default
    # path for the read.
    tracker = ImprovementTracker()
    summary = tracker.summary()
    try:
        limit = int(args.get("limit", 20) or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 1000))
    summary["proposed_samples"] = tracker.list_proposed()[
        :limit
    ]
    summary["applied_samples"] = tracker.list_applied()[
        :limit
    ]
    return summary


def _rule_quality_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Read-only lift-based quality metric across every rule
    in the RuleBook. Answers "are my learned rules actually
    helping?" — owner's T2 KPI. No LLM, no writes."""
    from core.learning.rule_quality import evaluate_rulebook
    report = evaluate_rulebook()
    try:
        limit = int(args.get("limit", 100) or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 10000))
    d = report.as_dict()
    d["rules"] = d["rules"][:limit]
    return d


def _analyze_competitor_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Scrape one or more public Shopify stores + (optionally)
    synthesise a strategic take via the LLM gateway. Auth-free:
    pulls from each store's public ``/products.json`` +
    ``/collections.json`` + homepage HTML.

    Each scrape appends to ``<storage_dir>/<store>.jsonl`` so
    repeat calls surface a ``diff`` against the previous run
    (new SKUs, median-price delta, new/lost apps). Disable with
    ``persist=false``.

    The tool touches LOCAL storage only (our own data/ dir) —
    it never writes to any competitor's store, never uses our
    Shopify token. Stays read-flagged for the MCP registry."""
    from agents.competitor_intel import (
        analyze_competitors, diff_vs_last,
        load_history, save_report,
    )

    stores_arg = args.get("stores") or []
    if isinstance(stores_arg, str):
        stores = [s.strip() for s in stores_arg.split(",") if s.strip()]
    else:
        stores = [
            str(s).strip()
            for s in stores_arg
            if str(s).strip()
        ]
    if not stores:
        raise ToolError("stores: must be a non-empty list")
    our_store = str(
        args.get("our_store") or "deguar.myshopify.com",
    )
    use_llm = bool(args.get("use_llm", True))
    persist = bool(args.get("persist", True))
    storage_dir = str(
        args.get("storage_dir") or "data/competitor_intel",
    )
    llm = None
    if use_llm:
        try:
            from core.llm_gateway import ask as _gateway_ask
        except Exception:  # noqa: BLE001
            _gateway_ask = None
        if _gateway_ask is not None:
            def llm(prompt: str) -> str:
                res = _gateway_ask(
                    prompt,
                    purpose="reasoning",
                    max_cost=0.02,
                    max_latency_ms=15_000,
                )
                if not res.ok:
                    raise RuntimeError(
                        res.error or "llm call failed",
                    )
                return res.text

    previous: dict[str, dict | None] = {}
    if persist:
        for s in stores:
            try:
                hist = load_history(
                    s, storage_dir=storage_dir, limit=1,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.debug(
                    "history pre-load failed for %s: %s", s, exc,
                )
                hist = []
            previous[s] = hist[-1] if hist else None

    reports = analyze_competitors(
        stores, our_store=our_store, llm=llm,
    )

    if persist:
        for r in reports:
            try:
                save_report(r, storage_dir=storage_dir)
            except Exception as exc:  # noqa: BLE001
                _logger.debug(
                    "persist failed for %s: %s",
                    r.store, exc,
                )

    payload_reports: list[dict[str, Any]] = []
    for r in reports:
        d = r.as_dict()
        if persist:
            d["diff"] = diff_vs_last(
                r, previous.get(r.store),
            )
        payload_reports.append(d)
    return {
        "our_store": our_store,
        "count": len(reports),
        "persisted": persist,
        "storage_dir": storage_dir if persist else "",
        "reports": payload_reports,
    }


def _competitor_history_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Read-only: return the last N persisted scrapes for one
    competitor store + a diff of the latest vs the one before.
    Answers the owner's "what changed on gymshark.com since
    last week?" question without re-scraping."""
    from agents.competitor_intel import load_history
    from agents.competitor_intel.agent import CompetitorReport

    store = str(args.get("store") or "").strip()
    if not store:
        raise ToolError("store: required")
    try:
        limit = int(args.get("limit", 10) or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 500))
    storage_dir = str(
        args.get("storage_dir") or "data/competitor_intel",
    )
    history = load_history(
        store, storage_dir=storage_dir, limit=limit,
    )
    diff: dict[str, Any] = {}
    if len(history) >= 2:
        # Re-hydrate the newest entry enough to run diff_vs_last
        # without pulling the full agent surface back into memory.
        from agents.competitor_intel import diff_vs_last
        from agents.competitor_intel.agent import (
            HomepageSignals, StoreCatalogSummary,
        )
        newest = history[-1]
        previous = history[-2]
        cat_d = newest.get("catalog") or {}
        hp_d = newest.get("homepage") or {}
        cat = StoreCatalogSummary(
            store=newest.get("store", store),
            product_count=int(cat_d.get("product_count") or 0),
            median_price=float(cat_d.get("median_price") or 0.0),
            top_products=list(cat_d.get("top_products") or []),
            newest_products=list(
                cat_d.get("newest_products") or [],
            ),
        )
        hp = HomepageSignals(
            apps_detected=list(hp_d.get("apps_detected") or []),
        )
        rehydrated = CompetitorReport(
            store=newest.get("store", store),
            scraped_at=float(newest.get("scraped_at") or 0.0),
            catalog=cat, homepage=hp,
        )
        diff = diff_vs_last(rehydrated, previous)
    elif len(history) == 1:
        diff = {"baseline": True}
    return {
        "store": store,
        "storage_dir": storage_dir,
        "count": len(history),
        "history": history,
        "latest_diff": diff,
    }


# ── Approval queue (Phase 2 of 4×4 matrix) ──────────────


def _budget_plan_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Run the Thompson-Sampling allocator on caller-supplied
    SKU performance records. Read-only — doesn't write to
    Meta Ads, just returns the plan."""
    from core.engines.budget_buyer import (
        BudgetAllocator, SKUPerformance,
    )
    perf_raw = args.get("performance") or []
    if not isinstance(perf_raw, list) or not perf_raw:
        raise ToolError("performance: non-empty list required")
    try:
        total = float(args.get("total_daily_usd") or 0)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            f"total_daily_usd: must be number ({exc})",
        )
    if total < 0:
        raise ToolError("total_daily_usd: must be >= 0")
    min_per = float(args.get("min_per_sku_usd") or 0)
    max_per_raw = args.get("max_per_sku_usd")
    max_per = (
        float(max_per_raw)
        if max_per_raw not in (None, "", 0, 0.0)
        else None
    )
    seed_raw = args.get("seed")
    seed = int(seed_raw) if seed_raw is not None else None

    perf: list = []
    for row in perf_raw:
        if not isinstance(row, dict):
            continue
        try:
            perf.append(SKUPerformance(
                sku=str(row.get("sku") or ""),
                product_id=str(row.get("product_id") or ""),
                orders=int(row.get("orders") or 0),
                revenue_usd=float(row.get("revenue_usd") or 0),
                ad_spend_usd=float(row.get("ad_spend_usd") or 0),
                impressions=int(row.get("impressions") or 0),
                clicks=int(row.get("clicks") or 0),
                days_active=max(
                    1, int(row.get("days_active") or 1),
                ),
            ))
        except ValueError as exc:
            raise ToolError(f"performance row: {exc}")

    allocator = BudgetAllocator(seed=seed)
    allocs = allocator.allocate(
        total, perf,
        min_per_sku_usd=min_per,
        max_per_sku_usd=max_per,
    )
    return {
        "total_daily_usd": total,
        "allocations": [a.as_dict() for a in allocs],
    }


def _ltv_stats_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Customer LTV summary + optional top-N customers."""
    from core.engines.budget_buyer import get_engine
    engine = get_engine()
    try:
        top = int(args.get("top", 0) or 0)
    except (TypeError, ValueError):
        top = 0
    payload: dict[str, Any] = {"stats": engine.ltv_stats()}
    if top > 0:
        top = min(top, 200)
        payload["top_customers"] = [
            c.as_dict()
            for c in engine.top_customers(limit=top)
        ]
    return payload


def _email_campaign_stats_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Read-only: per-flow stats from the email campaign
    engine. Owner asks Claude Desktop 'how are my lifecycle
    emails doing?' and gets pending/sent/failed counts per
    flow + total unsubscribes."""
    from core.engines.email_campaigns import get_engine
    return get_engine().stats()


def _pending_approvals_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Read-only: list HIGH/CRITICAL actions queued for owner
    confirm. Sweeps expired rows before returning so the view
    never shows stale 'pending' state."""
    from core.system.approval_queue import get_queue
    q = get_queue()
    q.expire_old()
    try:
        limit = int(args.get("limit", 20) or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 500))
    pending = q.pending()[:limit]
    return {
        "count": len(pending),
        "stats": q.stats(),
        "pending": [r.as_dict() for r in pending],
    }


def _approve_request_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Write-gated: approve a queued action by request_id.
    Idempotent — re-approving an already-approved row is a
    no-op (important for retry-prone Telegram webhooks)."""
    from core.system.approval_queue import get_queue
    request_id = str(args.get("request_id") or "").strip()
    if not request_id:
        raise ToolError("request_id: required")
    owner_id = str(args.get("owner_id") or "owner")
    reason = str(args.get("reason") or "")
    result = get_queue().approve(
        request_id, owner_id=owner_id, reason=reason,
    )
    if result is None:
        raise ToolError(f"no request with id {request_id}")
    return {
        "ok": result.status == "approved",
        "status": result.status,
        "request": result.as_dict(),
    }


def _deny_request_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Write-gated: deny a queued action by request_id."""
    from core.system.approval_queue import get_queue
    request_id = str(args.get("request_id") or "").strip()
    if not request_id:
        raise ToolError("request_id: required")
    owner_id = str(args.get("owner_id") or "owner")
    reason = str(args.get("reason") or "")
    result = get_queue().deny(
        request_id, owner_id=owner_id, reason=reason,
    )
    if result is None:
        raise ToolError(f"no request with id {request_id}")
    return {
        "ok": result.status == "denied",
        "status": result.status,
        "request": result.as_dict(),
    }


def _classify_action_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Read-only: ask the risk gate how a given action_type +
    payload would be classified. Useful for owner introspection
    ('is this HIGH or CRITICAL?') without triggering the action.
    """
    from core.system import risk_gate
    action_type = str(args.get("action_type") or "").strip()
    if not action_type:
        raise ToolError("action_type: required")
    payload = args.get("payload") or {}
    if not isinstance(payload, dict):
        raise ToolError("payload: must be an object")
    level = risk_gate.classify(action_type, payload)
    return {
        "action_type": action_type,
        "payload": dict(payload),
        "risk_level": level.value,
        "rank": level.rank(),
        "describe": risk_gate.describe(level),
        "requires_owner_approval":
            level.requires_owner_approval(),
    }


def _recent_cycles_handler(
    args: dict[str, Any],
) -> dict[str, Any]:
    """Tail the autopilot daemon log so the owner can ask
    Claude Desktop "what happened overnight" and get a
    structured summary.  Missing log file means the daemon
    hasn't started yet — handler returns a clean empty
    payload rather than crashing."""
    import json as _json
    from pathlib import Path as _P
    log_path = str(
        args.get("log_path")
        or "data/autopilot_loop.log",
    )
    try:
        limit = int(args.get("limit", 20) or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 1000))
    path = _P(log_path)
    if not path.exists():
        return {
            "log_path": log_path,
            "total": 0,
            "returned": 0,
            "cycles": [],
            "note": "log file does not exist yet",
        }
    cycles: list[dict[str, Any]] = []
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    cycles.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
    except OSError as exc:
        raise ToolError(
            f"cannot read log: {exc}",
        ) from exc
    tail = cycles[-limit:]
    return {
        "log_path": log_path,
        "total": len(cycles),
        "returned": len(tail),
        "cycles": tail,
    }


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
        name="trust_status",
        description=(
            "Per-source trust ranking — which data feeds "
            "ShopAI weights heaviest, sorted by current "
            "trust × freshness."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_trust_status_handler,
    ))
    reg.register(ToolSpec(
        name="memory_ladder",
        description=(
            "Episode → concept → procedure memory counts + "
            "promotion thresholds. Owner uses this to see "
            "what long-term patterns ShopAI has captured."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_memory_ladder_handler,
    ))
    reg.register(ToolSpec(
        name="recent_decisions",
        description=(
            "Recent decisions from the rationale ledger "
            "with their summaries. Pair with "
            "``explain_decision`` to drill into any row."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max decisions to return (1-200, "
                        "default 20)"
                    ),
                },
            },
        },
        handler=_recent_decisions_handler,
    ))
    reg.register(ToolSpec(
        name="predict_outcome",
        description=(
            "World-model what-if — given an action/kpi/"
            "context, return bias-adjusted mean + "
            "calibrated stdev + confidence band."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "kpi": {"type": "string"},
                "niche": {"type": "string"},
                "price_band": {"type": "string"},
                "margin_band": {"type": "string"},
                "tone": {"type": "string"},
            },
            "required": ["action", "kpi"],
        },
        handler=_predict_outcome_handler,
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
        name="doctor",
        description=(
            "Real connectivity probes — actually call "
            "Shopify, Meta Ads, fal.ai, Moby, and check the "
            "Obsidian vault path. Returns per-system ok + "
            "latency + fix hints."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "description": (
                        "HTTP timeout seconds (default 8)"
                    ),
                },
                "include_moby": {"type": "boolean"},
                "include_vault": {"type": "boolean"},
            },
        },
        handler=_doctor_handler,
    ))
    reg.register(ToolSpec(
        name="notify_errors",
        description=(
            "Compose + push a Telegram digest of recent "
            "autopilot cycle errors. Use dry_run=true to "
            "preview without sending."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "number",
                    "description": (
                        "Window to scan (hours, default 24)"
                    ),
                },
                "log_path": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "chat_id": {"type": "string"},
            },
        },
        handler=_notify_errors_handler,
        write=True,
    ))
    reg.register(ToolSpec(
        name="recent_deliberations",
        description=(
            "Last N structured decisions (5-pillar "
            "outcome/directions/constraints/refines/"
            "awareness records). Upstream of the "
            "rationale ledger — shows HOW each decision "
            "was reasoned through."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max records to return (1-200, "
                        "default 10)"
                    ),
                },
            },
        },
        handler=_recent_deliberations_handler,
    ))
    reg.register(ToolSpec(
        name="agents_list",
        description=(
            "List every agent registered with AgentManager "
            "— the lifecycle registry for specialised "
            "agents (content, finance, marketing, "
            "research, customer, ops). Optional type "
            "filter."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": (
                        "Filter by agent type; omit for "
                        "all."
                    ),
                },
            },
        },
        handler=_agents_list_handler,
    ))
    reg.register(ToolSpec(
        name="citations_show",
        description=(
            "Preview the owner-curated citations for a "
            "niche — what the GEO quote-sandwich wire "
            "would attach to product descriptions when "
            "use_geo_sandwich=True."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "niche": {
                    "type": "string",
                    "description": (
                        "Niche slug (e.g. pet, beauty); "
                        "default=\"default\""
                    ),
                },
            },
        },
        handler=_citations_show_handler,
    ))
    reg.register(ToolSpec(
        name="webhook_rate_limit_status",
        description=(
            "Per-IP webhook rate-limiter stats — active "
            "buckets, consumed/rejected counters, configured "
            "rate + burst. Flags webhook-endpoint abuse."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_webhook_rate_limit_status_handler,
    ))
    reg.register(ToolSpec(
        name="autopilot_status",
        description=(
            "Is the 24/7 autopilot daemon running? Combines "
            "pidfile liveness + latest cycle snapshot from "
            "the cycle log."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "log_path": {
                    "type": "string",
                    "description": (
                        "Override path to autopilot log "
                        "(default data/autopilot_loop.log)"
                    ),
                },
            },
        },
        handler=_autopilot_status_handler,
    ))
    reg.register(ToolSpec(
        name="recent_cycles",
        description=(
            "Tail the autopilot daemon log — recent "
            "24/7-loop cycles with launch counts, "
            "success counts, durations and errors."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Cycles to return (1-1000, "
                        "default 20)"
                    ),
                },
                "log_path": {
                    "type": "string",
                    "description": (
                        "Override path to autopilot log "
                        "(default data/autopilot_loop.log)"
                    ),
                },
            },
        },
        handler=_recent_cycles_handler,
    ))
    reg.register(ToolSpec(
        name="ingest_knowledge",
        description=(
            "Pull an external URL / file / raw text into the "
            "structured knowledge base so the oracle has "
            "source-cited facts. One of url / file / text "
            "required. Owner-gated (write)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "file": {"type": "string"},
                "text": {"type": "string"},
                "subject": {"type": "string"},
            },
        },
        handler=_ingest_knowledge_handler,
        write=True,
    ))
    reg.register(ToolSpec(
        name="analyze_failure",
        description=(
            "Root-cause analysis for a failed decision — "
            "contributing factors, lesson, suggested "
            "prevention rule. Owner supplies a failed "
            "episode; analyser returns structured read. "
            "Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "failed_episode": {
                    "type": "object",
                    "description": (
                        "{decision_type, action, "
                        "context: {...}}"
                    ),
                },
            },
            "required": ["failed_episode"],
        },
        handler=_analyze_failure_handler,
    ))
    reg.register(ToolSpec(
        name="ready_for_live",
        description=(
            "Pre-T1 go-live gate: env + doctor + learning "
            "loop (5-order synthetic replay) + live-health "
            "+ live-execution state. Single-verb verdict "
            "READY or BLOCKED with per-check fix list. "
            "Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "skip_learning_loop": {
                    "type": "boolean",
                    "description": (
                        "Skip the synthetic replay step "
                        "(use when daemon is already live)."
                    ),
                },
            },
        },
        handler=_ready_for_live_handler,
    ))
    reg.register(ToolSpec(
        name="live_health",
        description=(
            "Rolling health digest — doctor probes + recent "
            "autopilot cycles + engine feedback trends fused "
            "into verdict (healthy / degrading / "
            "needs_attention / unknown). Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cycles": {
                    "type": "integer",
                    "description": (
                        "Recent cycles to aggregate "
                        "(default 20, max 1000)."
                    ),
                },
            },
        },
        handler=_live_health_handler,
    ))
    reg.register(ToolSpec(
        name="brain_module_catalog",
        description=(
            "Honest map of the 225-module brain tree: which "
            "modules are active (wired into the decision "
            "flow), experimental (implemented + parked), "
            "archived, or unknown. Read-only."
        ),
        input_schema={
            "type": "object", "properties": {},
        },
        handler=_brain_module_catalog_handler,
    ))
    reg.register(ToolSpec(
        name="engine_feedback_stats",
        description=(
            "Per-engine execution ledger: success rate, avg "
            "elapsed, trend (improving / stable / declining), "
            "top errors. Populated automatically from every "
            "activator + publisher outcome via the engine "
            "outcome bus. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "engine": {
                    "type": "string",
                    "description": (
                        "Return one engine's detail; omit for "
                        "all-engines summary."
                    ),
                },
            },
        },
        handler=_engine_feedback_stats_handler,
    ))
    reg.register(ToolSpec(
        name="improvements_summary",
        description=(
            "Proposed improvements across learning engines — "
            "count + by-type distribution + samples of "
            "proposed / applied entries. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Sample size for proposed / applied "
                        "lists (default 20)."
                    ),
                },
            },
        },
        handler=_improvements_summary_handler,
    ))
    reg.register(ToolSpec(
        name="rule_quality",
        description=(
            "Lift-based quality read across every rule in the "
            "RuleBook — true positives, false positives, "
            "uncertain, insufficient data. Answers the T2 KPI "
            "'PatternMiner true-positive rate ≥ 60%'. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max rules to return (default 100)."
                    ),
                },
            },
        },
        handler=_rule_quality_handler,
    ))
    reg.register(ToolSpec(
        name="replay_orders",
        description=(
            "Replay a JSONL file of historical or synthetic "
            "Shopify order payloads through the live webhook "
            "pipeline — used to exercise the learning loop "
            "(Deliberation back-fill, engine outcome bus, "
            "PatternMiner) without waiting for real traffic."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to JSONL file, one order per "
                        "line."
                    ),
                },
                "throttle_s": {
                    "type": "number",
                    "description": (
                        "Sleep between orders (default 0)."
                    ),
                },
            },
            "required": ["path"],
        },
        handler=_replay_orders_handler,
        write=True,
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
        name="analyze_competitor",
        description=(
            "Scrape a public Shopify store's catalog + "
            "theme + installed apps + homepage signals. "
            "Optional LLM-synthesised strategic take. "
            "Each run appends to local JSONL history so "
            "repeat calls surface a diff (new SKUs, price "
            "moves, new apps). Reads target store's public "
            "/products.json; writes only our local data/."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "stores": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Competitor Shopify domains — e.g. "
                        "['allbirds.com', 'gymshark.com']."
                    ),
                },
                "our_store": {
                    "type": "string",
                    "description": (
                        "Our store (context for LLM insight)."
                    ),
                },
                "use_llm": {
                    "type": "boolean",
                    "description": (
                        "Run LLM synthesis after the raw "
                        "scrape (default true)."
                    ),
                },
                "persist": {
                    "type": "boolean",
                    "description": (
                        "Append to data/competitor_intel/ + "
                        "compute diff vs previous scrape "
                        "(default true)."
                    ),
                },
                "storage_dir": {
                    "type": "string",
                    "description": (
                        "Override storage directory "
                        "(default data/competitor_intel)."
                    ),
                },
            },
            "required": ["stores"],
        },
        handler=_analyze_competitor_handler,
    ))
    reg.register(ToolSpec(
        name="competitor_history",
        description=(
            "Return the last N persisted scrapes for a "
            "competitor store + a diff of the latest vs "
            "the previous scrape. Answers 'what changed "
            "on gymshark.com since last run?' without "
            "re-scraping. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "store": {
                    "type": "string",
                    "description": "Competitor domain.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max history rows (default 10, "
                        "max 500)."
                    ),
                },
                "storage_dir": {
                    "type": "string",
                    "description": (
                        "Override storage directory "
                        "(default data/competitor_intel)."
                    ),
                },
            },
            "required": ["store"],
        },
        handler=_competitor_history_handler,
    ))
    # ── Budget + Buyer engine ────────────────────────────
    reg.register(ToolSpec(
        name="budget_plan",
        description=(
            "Thompson-Sampling ad budget allocator. Caller "
            "supplies per-SKU performance (orders, revenue, "
            "ad_spend); returns recommended daily USD split. "
            "Read-only — does NOT push to Meta Ads."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "total_daily_usd": {
                    "type": "number",
                    "description": "Budget to split.",
                },
                "performance": {
                    "type": "array",
                    "description": (
                        "SKU performance records: sku, "
                        "orders, revenue_usd, ad_spend_usd, "
                        "clicks, impressions, days_active."
                    ),
                    "items": {"type": "object"},
                },
                "min_per_sku_usd": {"type": "number"},
                "max_per_sku_usd": {"type": "number"},
                "seed": {
                    "type": "integer",
                    "description": (
                        "RNG seed for reproducible samples."
                    ),
                },
            },
            "required": [
                "total_daily_usd", "performance",
            ],
        },
        handler=_budget_plan_handler,
    ))
    reg.register(ToolSpec(
        name="ltv_stats",
        description=(
            "Customer LTV summary — total customers, "
            "segment split (VIP / regular / one-time / "
            "dormant), avg + median LTV + GMV. Optional "
            "top=N returns the biggest spenders."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "top": {
                    "type": "integer",
                    "description": (
                        "Include top-N customers by spend "
                        "(0 = skip, max 200)."
                    ),
                },
            },
        },
        handler=_ltv_stats_handler,
    ))

    # ── Email campaigns ─────────────────────────────────
    reg.register(ToolSpec(
        name="email_campaign_stats",
        description=(
            "Read-only per-flow stats from the email "
            "campaign engine (welcome / abandoned-cart / "
            "post-purchase / win-back). Returns "
            "pending/sent/failed counts + unsubscribes."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_email_campaign_stats_handler,
    ))

    # ── Approval queue (Phase 2 of 4×4 matrix) ──────────
    reg.register(ToolSpec(
        name="pending_approvals",
        description=(
            "List HIGH/CRITICAL actions queued for owner "
            "confirm. Read-only. Expired rows swept before "
            "return so only actionable rows surface."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max rows (default 20, max 500)."
                    ),
                },
            },
        },
        handler=_pending_approvals_handler,
    ))
    reg.register(ToolSpec(
        name="approve_request",
        description=(
            "Approve a queued action by request_id. "
            "Idempotent — re-approving returns the existing "
            "row. Cannot un-deny or flip after expiry."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "Queued request_id.",
                },
                "owner_id": {
                    "type": "string",
                    "description": (
                        "Who approved (audit trail; default "
                        "'owner')."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Optional decision note.",
                },
            },
            "required": ["request_id"],
        },
        handler=_approve_request_handler,
        write=True,
    ))
    reg.register(ToolSpec(
        name="deny_request",
        description=(
            "Deny a queued action by request_id. Idempotent."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "Queued request_id.",
                },
                "owner_id": {
                    "type": "string",
                    "description": "Who denied.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why — visible in audit.",
                },
            },
            "required": ["request_id"],
        },
        handler=_deny_request_handler,
        write=True,
    ))
    reg.register(ToolSpec(
        name="classify_action",
        description=(
            "Read-only: ask the risk gate how an action_type "
            "+ payload would be classified. Useful for owner "
            "introspection without triggering the action."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": (
                        "Canonical action name (e.g. "
                        "'ad_campaign_create')."
                    ),
                },
                "payload": {
                    "type": "object",
                    "description": (
                        "Optional payload for "
                        "escalation-aware classification."
                    ),
                },
            },
            "required": ["action_type"],
        },
        handler=_classify_action_handler,
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
