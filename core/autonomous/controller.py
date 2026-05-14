"""AutonomousController — the main brain loop for autonomous store operation.

Connects all components into a single self-improving cycle:
  Data → Analysis → Decision → Action → Outcome → Learn → repeat

Each cycle:
  1. Fetch fresh store data (DataProvider)
  2. Run relevant engines (analysis, pricing, inventory, etc.)
  3. Convert engine output to proposed actions (DecisionExecutor)
  4. Execute approved actions (ActionExecutor)
  5. Track outcomes (OutcomeTracker)
  6. Learn from outcomes (LearningPipeline)
  7. Adjust future decisions based on learning
"""
from __future__ import annotations

import os
import time
import threading
from datetime import datetime, timezone
from typing import Any

from utils.logger import get_logger

logger = get_logger("autonomous")


# Maps cognitive hypothesis keywords to brain decision
# action types. When a hypothesis title contains a keyword,
# matching decisions get a cognitive boost.
_COGNITIVE_ACTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "image": ("add_images",),
    "photo": ("add_images",),
    "margin": ("raise_price", "lower_price"),
    "repriced": ("raise_price", "lower_price"),
    "pricing": ("raise_price", "lower_price"),
    "critical": ("fix_critical", "add_images", "lower_price"),
    "conversion": ("add_images", "lower_price"),
    "inventory": ("restock", "reorder"),
    "stockout": ("restock", "reorder"),
}


def _cognitive_action_hints(hypotheses: list) -> set[str]:
    """Extract brain action types implied by cognitive
    hypothesis titles so the ranking pass can boost them."""
    hints: set[str] = set()
    if not isinstance(hypotheses, list):
        return hints
    for h in hypotheses:
        if not isinstance(h, dict):
            continue
        title = h.get("title")
        if not isinstance(title, str):
            continue
        title_l = title.lower()
        for keyword, actions in _COGNITIVE_ACTION_KEYWORDS.items():
            if keyword in title_l:
                hints.update(actions)
    return hints


def _apply_cognitive_boost(
    decisions: list, hints: set[str],
) -> int:
    """Apply a 1.15x score boost to decisions whose action
    matches a cognitive hint. Writes an attribution entry
    under ``source='cognitive_hypothesis'``. Returns the
    number of decisions boosted."""
    if not hints or not decisions:
        return 0
    boosted = 0
    for d in decisions:
        if not isinstance(d, dict):
            continue
        action = d.get("type", "")
        if action not in hints:
            continue
        old_score = float(d.get("score", 0) or 0)
        new_score = round(old_score * 1.15, 3)
        d["score"] = new_score
        trail = d.setdefault("attribution", [])
        if isinstance(trail, list):
            trail.append({
                "source": "cognitive_hypothesis",
                "rule_id": f"cognitive:{action}",
                "description": (
                    f"cognitive hypothesis matched {action} → "
                    f"score boosted by 15%"
                ),
                "impact": round(new_score - old_score, 3),
            })
        boosted += 1
    return boosted


class AutonomousController:
    """Self-improving autonomous e-commerce controller."""

    def __init__(
        self,
        store_manager: Any = None,
        auto_approve: bool = False,
        *,
        cognitive_mind: Any = None,
        cognitive_mode: str = "off",
        use_engine_recommender: bool = False,
    ) -> None:
        """Build an autonomous controller.

        Args:
            store_manager: existing StoreManager (lazy created if None)
            auto_approve: skip human approval prompts when applying
                changes (production mode)
            cognitive_mind: optional core.cognitive.mind.Mind instance.
                When wired the controller can run a cognitive cycle
                alongside or instead of the legacy 5-phase loop.
            cognitive_mode: how the controller blends the cognitive
                Mind with the legacy loop. One of:
                  "off"      ignore cognitive Mind entirely (legacy
                             behavior — default for backwards compat)
                  "shadow"   run cognitive cycle AFTER the legacy
                             cycle, attach its report to the result,
                             but don't act on it
                  "primary"  run the cognitive cycle as the FIRST
                             phase; the legacy loop still runs but
                             the cognitive report carries the
                             recommendation
            use_engine_recommender: when True, the analysis phase
                picks engines via the brain-stack recommender
                (core.brain.engine_recommender) — letting the
                goal-feedback / EMA loop actually drive what runs.
                Falls back to the legacy hardcoded list on
                recommender failure or empty pick list. Default
                False for backward compatibility.
        """
        self._store_manager = store_manager
        self._auto_approve = auto_approve
        self._running = False
        self._cycle_count = 0
        self._cycle_thread: threading.Thread | None = None
        self._cycle_interval = 600  # 10 minutes default
        self._cycle_history: list[dict[str, Any]] = []
        self._max_history = 100

        # Components (lazy init)
        self._data_provider = None
        self._action_executor = None
        self._decision_executor = None
        self._learning_pipeline = None
        self._performance_tracker = None

        # Cognitive Mind integration
        self._cognitive_mind = cognitive_mind
        self._cognitive_mode = cognitive_mode if cognitive_mode in (
            "off", "shadow", "primary",
        ) else "off"

        # Brain-stack engine recommender opt-in
        self._use_engine_recommender = use_engine_recommender

        # Wave 6 #19d: lock for lazy-init of _reflection_synth and
        # _error_buffer so concurrent cycle threads don't race on the
        # check-and-set. The synthesizer and buffer are initialised
        # on first use (in _run_reflection_hook) — not here — to
        # avoid eagerly importing the reflection package.
        self._reflection_init_lock = threading.Lock()
        self._reflection_synth = None
        self._error_buffer = None

        # Vault sync rate limiting — track the last auto-export
        # timestamp so we don't hammer the filesystem every cycle
        # when no new patterns have been promoted, but still run an
        # opportunistic check once per hour to pick up out-of-band
        # learned records (e.g. manual memory ingests).
        #
        # The lock guards the check-and-update so two concurrent
        # cycle threads can't both pass the rate gate on the same
        # tick. We hold it ONLY across the check/reserve section —
        # the actual bridge.export_knowledge() call happens outside
        # the critical section so a slow export never blocks the
        # other cycle's reflection hook.
        self._vault_export_lock = threading.Lock()
        self._last_vault_export_ts: float = 0.0
        self._vault_import_done: bool = False
        self._vault_min_export_interval_sec: float = 3600.0

    def initialize(self, store_manager: Any = None) -> dict[str, Any]:
        """Initialize all components."""
        if store_manager:
            self._store_manager = store_manager

        if not self._store_manager:
            from data_pipeline.store.store_manager import StoreManager
            self._store_manager = StoreManager()

        from data_pipeline.store.data_provider import DataProvider
        from execution.action_executor import ActionExecutor, DecisionExecutor

        self._data_provider = DataProvider(self._store_manager)
        self._action_executor = ActionExecutor(self._store_manager)
        self._action_executor.set_auto_approve(self._auto_approve)
        self._decision_executor = DecisionExecutor(self._action_executor)

        self._learning_pipeline = LearningPipeline(self._store_manager)
        self._performance_tracker = PerformanceTracker(self._store_manager)

        # System layer integration
        try:
            from core.memory.unified_memory import get_unified_memory
            from core.system.llm_adapter import get_llm
            from core.system.adaptive_skills import get_adaptive_skills
            from core.autonomous.layer_dispatcher import LayerDispatcher
            from core.autonomous.agent_dispatcher import AgentDispatcher
            self._unified_memory = get_unified_memory()
            self._unified_memory.initialize()
            self._memory = self._unified_memory._shared  # Backward compat
            self._llm = get_llm()
            self._skills = get_adaptive_skills()
            self._layer_dispatcher = LayerDispatcher()
            self._layer_dispatcher.initialize()
            self._agent_dispatcher = AgentDispatcher()
            self._agent_dispatcher.initialize()

            # ── Adapter layer ──
            #
            # Wire the brain to the universal adapter ecosystem.
            # Bootstrap calls register every available adapter into
            # the process-wide ``AdapterRegistry``:
            #
            #   * LLM (Groq, Gemini, DeepSeek, Mistral, Ollama,
            #     OpenRouter, HuggingFace, OpenAI, Anthropic)
            #   * Shopify native (risk, inventory, fulfillment,
            #     metafield)
            #   * Web search (Brave, Serper, DDGS)
            #   * Shipping (EasyPost, Shippo)
            #   * Email (Brevo, Resend, SendGrid, Klaviyo)
            #   * SMS (Twilio)
            #   * Payment (PayPal, Stripe)
            #   * Image (DALL-E 3)
            #   * Knowledge base (Obsidian)
            #   * Browser (Playwright)
            #   * Vector DB (Weaviate)
            #   * Scraper (Firecrawl)
            #   * Reviews (Judge.me)
            #
            # Adapters whose credentials are unset still register;
            # the smart router skips them via ``is_configured()``.
            # The brain + agent dispatcher pick up ``get_router()``
            # lazily, so failures here MUST NOT take down the
            # rest of the controller — the legacy ``self._llm``
            # path keeps working as before.
            # Each adapter family is registered independently so a
            # missing-module / bootstrap-failure on one doesn't sink
            # the rest. The router itself is always populated as long
            # as `core.adapters` imports — individual register_all()
            # failures get logged and skipped.
            try:
                from core.adapters import get_router
                self._adapter_status = {}
                _ADAPTER_FAMILIES = (
                    "llm", "shopify", "search", "shipping",
                    "email", "sms", "payment", "image",
                    "obsidian", "browser", "vector", "scraper",
                    "reviews", "ads", "ads_spy", "video_gen",
                    "sourcing", "subscription", "voice",
                    "automation", "helpdesk", "analytics", "crm",
                )
                _registered_per_family: dict[str, int] = {}
                for family in _ADAPTER_FAMILIES:
                    try:
                        mod = __import__(
                            f"core.adapters.{family}.bootstrap",
                            fromlist=["register_all"],
                        )
                        family_status = mod.register_all() or {}
                    except ModuleNotFoundError:
                        # Adapter family not present in this build.
                        # Expected for optional integrations the
                        # operator hasn't installed.
                        _registered_per_family[family] = 0
                        continue
                    except Exception as fam_exc:  # noqa: BLE001
                        logger.warning(
                            "Adapter family %s failed to register: %s",
                            family, fam_exc,
                        )
                        _registered_per_family[family] = 0
                        continue
                    self._adapter_status.update(family_status)
                    _registered_per_family[family] = len(family_status)
                self._adapter_router = get_router()
                logger.info(
                    "Adapter layer initialised: %d adapters registered, "
                    "%d configured across families: %s",
                    len(self._adapter_status),
                    sum(1 for v in self._adapter_status.values() if v),
                    ", ".join(
                        f"{f}={n}" for f, n
                        in _registered_per_family.items() if n
                    ),
                )
            except Exception as adapter_exc:  # noqa: BLE001
                logger.warning(
                    "Adapter layer initialisation failed (continuing without it): %s",
                    adapter_exc,
                )
                self._adapter_status = {}
                self._adapter_router = None

            self._init_error: str = ""
        except Exception as exc:  # noqa: BLE001
            # Previously this block silently set every subsystem to
            # None and emitted a successful "initialized" log line —
            # operators had no idea memory/LLM/dispatchers had failed
            # to load. Capture the failure with a full traceback,
            # remember it on the controller, and emit a loud warning.
            logger.exception(
                "AutonomousController initialization failed: %s", exc,
            )
            self._unified_memory = None
            self._memory = None
            self._llm = None
            self._skills = None
            self._layer_dispatcher = None
            self._agent_dispatcher = None
            self._adapter_router = None
            self._adapter_status = {}
            self._init_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "AutonomousController running in degraded mode "
                "(no memory / LLM / dispatchers / adapters): %s", self._init_error,
            )

        if getattr(self, "_init_error", ""):
            logger.info(
                "AutonomousController initialized (DEGRADED: %s)",
                self._init_error,
            )
            return {
                "status": "degraded",
                "error": self._init_error,
                "auto_approve": self._auto_approve,
            }

        # Obsidian vault — one-shot import on boot so hand-written
        # notes in Concepts/Knowledge/Decisions land in UnifiedMemory
        # before the first run_cycle. Best-effort: a missing vault
        # or failing memory instance must never block initialisation.
        self._maybe_import_vault_on_boot()

        logger.info("AutonomousController initialized")
        return {"status": "initialized", "auto_approve": self._auto_approve}

    # ── Obsidian boot import ─────────────────────────────────

    def _maybe_import_vault_on_boot(self) -> dict[str, Any]:
        """Scan the configured Obsidian vault once on startup and
        ingest every ``.md`` note into UnifiedMemory.

        Idempotent — once a successful import has run in this
        process, subsequent calls return an empty report without
        re-walking the vault. The bridge itself also skips notes
        whose content hash hasn't changed, so even when operators
        call ``initialize()`` multiple times the incremental cost
        is O(0) after the first run.

        Returns the bridge's import report so callers/tests can
        inspect the counts. Silently returns an empty report when
        the vault is unconfigured, unreachable, or already
        imported in this process.
        """
        empty = {"imported": 0, "skipped": 0, "errors": 0}
        if getattr(self, "_vault_import_done", False):
            return empty
        try:
            from core.adapters.config import get_config
            vault_path = get_config().get("obsidian_vault_path")
            if not vault_path:
                return empty
            if self._unified_memory is None:
                return empty
            from core.adapters.obsidian.memory_bridge import VaultMemoryBridge
            bridge = VaultMemoryBridge(vault_path)
            result = bridge.import_vault(self._unified_memory)
            # Mark done only on a clean run so a transient failure
            # (e.g. vault path was a symlink dangling at boot) gets
            # another attempt next time initialize() is called.
            self._vault_import_done = True
            if result.get("imported", 0) or result.get("errors", 0):
                logger.info(
                    "Vault boot import: %d imported, %d skipped, %d errors",
                    result.get("imported", 0),
                    result.get("skipped", 0),
                    result.get("errors", 0),
                )
            return result
        except Exception as exc:  # noqa: BLE001
            # Visible at default INFO/WARNING log level so operators
            # don't silently lose vault-backed memory on boot. The
            # "not configured" case short-circuits above — reaching
            # this branch always signals a real failure (missing
            # module, unreadable path, bridge error).
            logger.warning("Vault boot import skipped: %s", exc)
            return empty

    # ── Single Cycle ─────────────────────────────────────────

    def run_cycle(self, store_id: str = "") -> dict[str, Any]:
        """Run one full autonomous cycle."""
        sid = store_id or (self._store_manager.active_store_id if self._store_manager else "")
        if not sid:
            return {"status": "error", "error": "No store specified"}

        self._cycle_count += 1
        cycle_id = f"cycle_{self._cycle_count}_{int(time.time())}"
        start = time.monotonic()

        logger.info("Starting cycle %s for store %s", cycle_id, sid)

        # Per-cycle error ledger. Pre-fix every phase caught its
        # own exception with ``except Exception: logger.debug(...)``
        # and the failure was invisible at the default INFO log
        # level — operators had no way to diagnose why a cycle
        # ran with degraded intelligence. Core audit flagged this
        # as 23+ silent failure points. The ``_record`` helper
        # below promotes every catch to a WARNING log AND
        # appends the typed error string to this dict, which is
        # surfaced on ``cycle_result["phase_errors"]`` at the end
        # of the run so ``cli.py auto`` and the observability
        # dashboard can display which subsystems failed and why.
        phase_errors: dict[str, str] = {}

        def _record(phase_name: str, exc: BaseException) -> None:
            err = f"{type(exc).__name__}: {exc}"
            phase_errors[phase_name] = err
            logger.warning("cycle phase %r failed: %s", phase_name, err)

        # Clear working memory from previous cycle
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
            mi.clear_working()
        except Exception as exc:
            _record("working_memory_clear", exc)

        cycle_result: dict[str, Any] = {
            "cycle_id": cycle_id,
            "store_id": sid,
            "cycle_number": self._cycle_count,
            "phases": {},
        }

        # Phase 0: TIME + CONTEXT awareness
        try:
            from core.brain.smart_rotation import get_time_awareness, get_exploration_boost
            ta = get_time_awareness()
            time_ctx = ta.get_context()
            cycle_result["phases"]["time_context"] = {
                "period": time_ctx.get("period", ""),
                "day": time_ctx.get("day", ""),
                "season": time_ctx.get("season", ""),
                "signals": time_ctx.get("signals", []),
                "shopping_intensity": time_ctx.get("shopping_intensity", 0.5),
            }
            # Check exploration
            eb = get_exploration_boost()
            explore = eb.should_explore()
            if explore.get("explore"):
                cycle_result["phases"]["exploration_alert"] = explore
        except Exception as exc:
            _record("exploration_boost", exc)

        # Phase 1: DATA — Fetch current store state
        data = self._phase_data(sid)
        cycle_result["phases"]["data"] = {
            "products": len(data.get("products", [])),
            "orders": len(data.get("order_data", [])),
            "customers": len(data.get("customer_data", [])),
            "source": data.get("source", "unknown"),
        }

        # Phase 1-pre: PRICE HISTORY — record current prices
        try:
            from data_pipeline.tracking.price_history import get_price_history
            ph = get_price_history()
            recorded = ph.record_prices_batch(data.get("products", []), store_id=sid)
            if recorded:
                cycle_result["phases"]["price_tracking"] = {"new_prices": recorded}
        except Exception as exc:
            _record("price_history", exc)

        # Phase 1a: DATA QUALITY — validate and score data before AI uses it
        try:
            from data_pipeline.quality import get_data_quality
            dq = get_data_quality()
            quality_report = dq.run(data)
            cycle_result["phases"]["data_quality"] = {
                "score": quality_report.get("overall_score", 0),
                "products_valid": quality_report["products"]["valid"],
                "issues": len(quality_report.get("issues", [])),
                "anomalies": len(quality_report.get("anomalies", [])),
                "top_issue": quality_report["issues"][0]["message"][:80] if quality_report.get("issues") else "none",
            }
            # Use cleaned products for all subsequent phases
            if quality_report.get("cleaned_products"):
                data["products"] = quality_report["cleaned_products"]
        except Exception as exc:
            _record("data_quality_pipeline", exc)

        # Populate unified memory (skip if same data as last cycle)
        _data_key = f"{sid}_{len(data.get('products', []))}_{len(data.get('order_data', []))}"
        if not hasattr(self, '_last_data_key') or self._last_data_key != _data_key:
            self._last_data_key = _data_key
            if hasattr(self, '_unified_memory') and self._unified_memory:
                self._unified_memory.ingest_store_data(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                    sid,
                )
            elif self._memory:
                self._memory.load_store_data(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                    sid,
                )

        # Get skill recommendations
        if self._skills:
            recommended = self._skills.recommend_skills({
                "products": data.get("products", []),
                "orders": data.get("order_data", []),
                "customers": data.get("customer_data", []),
            })
            cycle_result["phases"]["skills"] = {
                "recommended": len(recommended),
                "top": [r["name"] for r in recommended[:5]],
            }

        # Phase 1c: COMPETITOR SCAN — get real market data
        try:
            from core.ai.competitor_monitor import get_competitor_monitor
            cm = get_competitor_monitor()
            comp_scan = cm.scan_competitors(data.get("products", []), max_products=5)
            cycle_result["phases"]["competitor_scan"] = {
                "products_scanned": comp_scan.get("products_scanned", 0),
                "position": comp_scan.get("summary", {}),
            }
            # Inject competitor data into store data for brain/engines
            data["competitor_data"] = comp_scan.get("results", [])
            data["market_position"] = comp_scan.get("summary", {})
        except Exception as exc:
            _record("competitor_scan", exc)

        # Phase 1a-goal: GOAL SELECTION — choose strategic goal
        #
        # Pre-fix the GoalManager existed but was orphaned from
        # the cycle — only CoreOrchestrator called it and the
        # brain had no parameter to receive the goal. Core
        # audit flagged this as the #1 CRITICAL weakness
        # (goal-system dead code). Fix A wires it in:
        #   1. build a situation dict from the current cycle data
        #   2. call GoalManager.select_goal(situation, cycle_num)
        #   3. pass the chosen goal to brain.think(data, goal=...)
        # Failures here are non-fatal — when selection fails,
        # the brain falls back to the severity-only ranking
        # that existed before Fix A (``goal=None``).
        selected_goal: str | None = None
        goal_reason = ""
        try:
            from core.goals.goal_manager import GoalManager
            if not hasattr(self, "_goal_manager") or self._goal_manager is None:
                self._goal_manager = GoalManager()
            situation = {
                "financial": {
                    "health_grade": cycle_result["phases"].get("data", {}).get("source", "B"),
                    "critical_alerts": 0,
                },
                "customers": {
                    "churn_risk_pct": 0,
                    "total_customers": len(data.get("customer_data", [])),
                },
                "inventory": {
                    "total_products": len(data.get("products", [])),
                },
                "health": {
                    "overall_grade": "B",
                },
            }
            goal_result = self._goal_manager.select_goal(
                situation, cycle_number=self._cycle_count,
            )
            selected_goal = goal_result.get("goal", "maximize_profit")
            goal_reason = goal_result.get("reason", "")
            cycle_result["phases"]["goal"] = {
                "selected": selected_goal,
                "reason": goal_reason[:120],
                "switched": bool(goal_result.get("switched", False)),
                "confidence": float(goal_result.get("confidence", 0) or 0),
            }
        except Exception as exc:
            _record("goal_selection", exc)

        # Phase 1b: BRAIN THINK — autonomous reasoning
        try:
            from core.brain.decision_brain import DecisionBrain
            brain = DecisionBrain()
            thought = brain.think(data, goal=selected_goal)
            # Record exploration
            try:
                from core.brain.smart_rotation import get_exploration_boost
                eb = get_exploration_boost()
                eb.record(thought.get("action_plan", [{}])[0].get("action", "analyze") if thought.get("action_plan") else "analyze")
            except Exception as exc:
                _record("exploration_record", exc)

            # Pre-fix the phase summary dropped every adapter-
            # layer signal the brain surfaced (``ai_reasoning``,
            # ``via``, ``adapter``, ``model``) so operators had
            # no way to tell which LLM answered. Surface the
            # relevant fields so ``cli.py auto`` and the
            # observability dashboard can display them.
            ai_reasoning = thought.get("ai_reasoning") or {}
            # Surface structured_decisions so the per-product
            # memory-informed pricing trail (with Fix H
            # attribution) reaches downstream consumers.
            structured_decisions = thought.get("structured_decisions", []) or []
            brain_summary = {
                "health_score": thought.get("health_score", 0),
                "problems": len(thought.get("problems", [])),
                "opportunities": len(thought.get("opportunities", [])),
                "decisions": len(thought.get("decisions", [])),
                "top_action": thought["action_plan"][0]["action"] if thought.get("action_plan") else "none",
                "structured_decisions": structured_decisions,
                "structured_decisions_count": len(structured_decisions),
            }
            if isinstance(ai_reasoning, dict) and ai_reasoning.get("available"):
                brain_summary["ai_available"] = True
                brain_summary["ai_via"] = ai_reasoning.get("via", "")
                brain_summary["ai_adapter"] = ai_reasoning.get("adapter", "")
                brain_summary["ai_model"] = ai_reasoning.get("model", "")
                if ai_reasoning.get("tokens_in") or ai_reasoning.get("tokens_out"):
                    brain_summary["ai_tokens_in"] = ai_reasoning.get("tokens_in", 0)
                    brain_summary["ai_tokens_out"] = ai_reasoning.get("tokens_out", 0)
            else:
                brain_summary["ai_available"] = False
            cycle_result["phases"]["brain"] = brain_summary
            # Store brain decisions for phase 3
            cycle_result["_brain_decisions"] = thought.get("decisions", [])
        except Exception as exc:
            _record("brain_think", exc)
            thought = {}

        # Store brain context in working memory for other phases
        try:
            mi.set_working("health_score", thought.get("health_score", 0))
            mi.set_working("top_problems", thought.get("problems", [])[:3])
            mi.set_working("top_opportunities", thought.get("opportunities", [])[:3])
        except Exception as exc:
            _record("working_memory_store", exc)

        # Phase 1d: COGNITIVE THINKING — deep understanding + reasoning
        try:
            from core.brain.cognitive import get_cognitive_module
            cog = get_cognitive_module()

            # Get recent memories for analysis
            cog_memories = []
            if hasattr(self, '_unified_memory') and self._unified_memory:
                try:
                    cog_memories = self._unified_memory._memory_intel.retrieve(
                        "pricing", limit=20) if self._unified_memory._memory_intel else []
                except Exception as exc:
                    _record("cognitive_memory_retrieve", exc)

            rules = []
            if hasattr(self, '_unified_memory') and self._unified_memory:
                try:
                    rules = self._unified_memory.get_learned_rules()
                except Exception as exc:
                    _record("cognitive_rules_retrieve", exc)

            # Deep analysis (limit products for speed)
            deep = cog.think_deep(data.get("products", [])[:5], cog_memories, rules)
            # Fix Q: apply cognitive hypothesis hints to the
            # brain's decisions before phase 3 rank consumes
            # them. Pre-fix cognitive was a write-only
            # dashboard key; now hypothesis titles steer the
            # ranking.
            hypothesis_list = deep["reasoning"].get("hypothesis_list", [])
            hints = _cognitive_action_hints(hypothesis_list)
            decisions_boosted = _apply_cognitive_boost(
                thought.get("decisions", []) if isinstance(thought, dict) else [],
                hints,
            )
            # Re-sort now that scores have shifted so phase 3
            # sees the boosted ranking.
            if decisions_boosted and isinstance(thought, dict):
                thought["decisions"] = sorted(
                    thought.get("decisions", []),
                    key=lambda d: (-float(d.get("score", 0) or 0), d.get("priority", 5)),
                )
                cycle_result["_brain_decisions"] = thought["decisions"]
            cycle_result["phases"]["cognitive"] = {
                "products_analyzed": deep["understanding"]["products_analyzed"],
                "critical_products": deep["understanding"]["critical"],
                "clusters": deep["understanding"]["clusters"],
                "hypotheses": deep["reasoning"]["hypotheses"],
                "near_misses": deep["failure_analysis"]["near_misses"],
                "questions": deep["curiosity"]["questions"][:3],
                "exploration": deep["curiosity"]["exploration"].get("suggest", ""),
                "decisions_boosted": decisions_boosted,
            }

            # Record exploration. Previously this loop referenced
            # ``brain_decisions`` which is only assigned later (phase
            # 3, line ~470), so every iteration raised NameError and
            # was silently swallowed by the enclosing try/except —
            # meaning cognitive curiosity tracking has been dark
            # since the phase was added. Pull from the ``thought``
            # object returned by ``brain.think(data)`` instead, which
            # is the canonical source for this cycle's decisions.
            for dec in thought.get("decisions", []) if isinstance(thought, dict) else []:
                cog.curiosity.record_exploration(dec.get("type", "unknown"))

            # Track confidence calibration from recent decisions
            for m in cog_memories[:10]:
                action = m.get("action", "")
                confidence = m.get("confidence", 0.5)
                score = m.get("score", 3.0)
                if action:
                    cog.reflection.record_decision(action, confidence, score)
        except Exception as exc:
            _record("cognitive_thinking", exc)

        # Phase 1f: RL PRICING — learned pricing recommendations
        try:
            from models.rl.pricing_agent import get_pricing_agent
            rl = get_pricing_agent()
            # Learn from memory every 5 cycles
            learn_result = {}
            if self._cycle_count % 5 == 1:
                learn_result = rl.learn_from_memory()
            # Get recommendations
            rl_recs = rl.recommend_all(data.get("products", [])[:5])
            cycle_result["phases"]["rl_pricing"] = {
                "recommendations": len(rl_recs),
                "learned_from": learn_result.get("learned", 0),
                "top_action": rl_recs[0]["action"] if rl_recs else "none",
                "avg_confidence": round(
                    sum(r["confidence"] for r in rl_recs) / max(len(rl_recs), 1), 2
                ),
            }
        except Exception as exc:
            _record("rl_pricing", exc)

        # Phase 1g: CUSTOMER SEGMENTATION — segment customers
        try:
            from models.ml.customer_segmentation import get_customer_segmentation
            seg = get_customer_segmentation()
            seg_result = seg.segment(data.get("customer_data", []))
            if seg_result.get("total_customers", 0) > 0:
                cycle_result["phases"]["segmentation"] = {
                    "customers": seg_result.get("total_customers", 0),
                    "segments": seg_result.get("segment_distribution", {}),
                }
        except Exception as exc:
            _record("segmentation", exc)

        # Phase 1h: DEMAND FORECASTING — predict future demand
        try:
            from models.ml.demand_forecast import get_demand_forecaster
            fc = get_demand_forecaster()
            fc_result = fc.forecast(
                data.get("products", []),
                data.get("order_data", []),
            )
            cycle_result["phases"]["demand_forecast"] = {
                "products": fc_result.get("total_products", 0),
                "restock_needed": fc_result.get("restock_needed", 0),
                "trends": fc_result.get("trend_summary", {}),
            }
        except Exception as exc:
            _record("demand_forecast", exc)

        # Phase 1i: IMAGE SOURCING — find images for products without them
        try:
            from execution.content.image_sourcer import get_image_sourcer
            sourcer = get_image_sourcer()
            img_result = sourcer.source_images(data.get("products", []), max_products=5)
            if img_result.get("images_found", 0) > 0:
                cycle_result["phases"]["image_sourcing"] = {
                    "products_needing": img_result.get("products_without_images", 0),
                    "images_found": img_result.get("images_found", 0),
                    "method": img_result.get("method", ""),
                }
        except Exception as exc:
            _record("image_sourcing", exc)

        # Phase 2: ANALYZE — Run analysis engines
        analysis = self._phase_analyze(sid, data)
        total_insights = 0
        _insight_keys = (
            "recommendations", "winners", "ranked_products",
            "reorder_plan", "alerts", "segments",
            "reorder_recommendations", "opportunities",
        )
        for a in analysis.values():
            if isinstance(a, dict) and a.get("status") != "error":
                d = a.get("data")
                if isinstance(d, dict):
                    for key in _insight_keys:
                        val = d.get(key)
                        if isinstance(val, list):
                            total_insights += len(val)
                    if d.get("recommended_price"):
                        total_insights += 1
        cycle_result["phases"]["analysis"] = {
            "engines_run": len([a for a in analysis.values() if isinstance(a, dict) and a.get("status") != "error"]),
            "insights": total_insights,
        }

        # Phase 2b: LAYERS — Run all 12 layers (131 engines grouped by domain)
        if hasattr(self, '_layer_dispatcher') and self._layer_dispatcher:
            try:
                layer_result = self._layer_dispatcher.run_all(data)
                cycle_result["phases"]["layers"] = {
                    "layers_run": layer_result.get("layers_run", 0),
                    "total_insights": layer_result.get("total_insights", 0),
                    "duration_s": layer_result.get("duration_s", 0),
                }
                total_insights += layer_result.get("total_insights", 0)
            except Exception as exc:  # noqa: BLE001
                # Promoted from debug → warning so operators see
                # broken layer phases at default log level. The
                # cycle_result phase entry already carries the
                # error string for downstream callers.
                logger.warning(
                    "AutonomousController: layer dispatch raised: %s", exc,
                )
                cycle_result["phases"]["layers"] = {"error": str(exc)[:80]}

        # Phase 3: DECIDE — Convert brain decisions + analysis to actions
        brain_decisions = cycle_result.get("_brain_decisions", [])
        decisions = self._phase_decide(sid, analysis, brain_decisions)
        cycle_result["phases"]["decisions"] = {
            "proposed": len(decisions),
            "types": list(set(d.get("type", "") for d in decisions)),
        }

        # Phase 3b: AGENTS — Dispatch decisions to domain agents
        if hasattr(self, '_agent_dispatcher') and self._agent_dispatcher:
            try:
                agent_result = self._agent_dispatcher.dispatch(
                    brain_decisions, {"products": data.get("products", []),
                                      "orders": data.get("order_data", []),
                                      "customers": data.get("customer_data", [])},
                )
                # Pre-fix the summary dropped the
                # ``router_attached`` flag the dispatcher added
                # to its result envelope, so operators had no way
                # to tell whether agents actually had the
                # SmartRouter available during dispatch.
                cycle_result["phases"]["agents"] = {
                    "dispatched": agent_result.get("dispatched", 0),
                    "agents_available": agent_result.get("agents_available", 0),
                    "router_attached": bool(agent_result.get("router_attached", False)),
                }
            except Exception as exc:
                _record("agent_dispatch", exc)
                cycle_result["phases"]["agents"] = {"error": str(exc)[:80]}

        # Phase 4: EXECUTE — Smart execution with simulation + learning
        executions = self._phase_execute()

        # Phase 4a: SMART EXECUTION — simulate all pending decisions
        smart_exec_result = {}
        try:
            from execution.smart_executor import get_smart_executor
            se = get_smart_executor()
            pending = self._action_executor.get_pending() if self._action_executor else []
            if pending:
                smart_exec_result = se.execute_batch(pending, store_data=data)
                cycle_result["phases"]["smart_execution"] = {
                    "total": smart_exec_result.get("total", 0),
                    "simulated": smart_exec_result.get("simulated", 0),
                    "dry_run": smart_exec_result.get("dry_run", 0),
                    "live": smart_exec_result.get("live", 0),
                    "avg_score": smart_exec_result.get("avg_score", 0),
                }
                # Smart execution handles these, clear from pending
                if self._action_executor:
                    self._action_executor._pending_actions.clear()
        except Exception as exc:
            _record("smart_execution", exc)

        cycle_result["phases"]["execution"] = {
            "executed": len([e for e in executions if e.get("status") == "executed"]),
            "smart_executed": smart_exec_result.get("total", 0),
            "failed": len([e for e in executions if e.get("status") == "failed"]),
            "pending": len(self._action_executor.get_pending()) if self._action_executor else 0,
        }

        # Phase 4b: INTELLIGENCE CYCLE — run full AI cycle on key decisions
        if hasattr(self, '_unified_memory') and self._unified_memory:
            try:
                ic_results = []
                categories = ["product", "pricing", "marketing"]
                for cat in categories:
                    ic_result = self._unified_memory.run_intelligence_cycle(
                        category=cat, data=data, store_id=sid,
                    )
                    ic_results.append(ic_result)
                cycle_result["phases"]["intelligence_cycle"] = {
                    "cycles_run": len(ic_results),
                    "avg_score": round(
                        sum(r.get("score", 0) for r in ic_results) / max(len(ic_results), 1), 1
                    ),
                    "actions": [r.get("action", "none") for r in ic_results],
                    "memory_informed": sum(1 for r in ic_results if r.get("memory_informed")),
                }
            except Exception as exc:
                _record("intelligence_cycle", exc)

            # Capture engine results into data architecture
            try:
                for engine_name, result in analysis.items():
                    if isinstance(result, dict) and result.get("status") != "error":
                        self._unified_memory.capture_data(
                            domain="tool_usage",
                            data={"tool_name": engine_name, "success": True,
                                  "output_size": len(str(result))},
                            source="engine",
                            store_id=sid,
                        )
            except Exception as exc:
                _record("engine_memory_mirror", exc)

        # Phase 5: LEARN — Track outcomes via all learning systems
        # Merge smart execution results into executions for learning
        all_executions = list(executions)
        se_results = smart_exec_result.get("results", []) if isinstance(smart_exec_result, dict) else []
        for se in se_results:
            all_executions.append({
                "engine": se.get("action_type", "smart_executor"),
                "type": se.get("action_type", ""),
                "status": "executed",
                "score": se.get("score", 3.0),
                "mode": se.get("mode", "simulate"),
                "duration_s": se.get("duration_s", 0),
            })

        # Feed smart-execution outcomes into the ActionWeightStore.
        # Per-item isolation so one bad record() call can't drop
        # the remaining items; counts are surfaced on the learning
        # phase (weight_updates + weight_store_update_failures).
        # Write key is (action_type, action_type): SmartExecutor
        # works on action types, not brain decision categories —
        # aligning the two naming spaces is a separate refactor.
        weight_updates = 0
        weight_store_update_failures = 0
        try:
            from core.learning.action_weights import get_action_weight_store
            _weight_store = get_action_weight_store()
        except Exception as exc:
            # Top-level import/singleton failure → route through
            # phase_errors; per-item failures use the counter.
            _record("weight_store_update", exc)
            _weight_store = None

        if _weight_store is not None:
            for se in se_results:
                action_type = str(se.get("action_type", "") or "")
                if not action_type:
                    continue
                try:
                    score = float(se.get("score", 0) or 0)
                    _weight_store.record(action_type, action_type, score)
                    weight_updates += 1
                except Exception as exc:  # noqa: BLE001
                    weight_store_update_failures += 1
                    logger.error(
                        "weight_store.record failed for action=%s: %s",
                        action_type, exc,
                    )
            if weight_store_update_failures > 0:
                logger.error(
                    "weight store: %d/%d outcomes failed to land "
                    "this cycle — learning signal may drift",
                    weight_store_update_failures,
                    weight_updates + weight_store_update_failures,
                )

        learning = self._phase_learn(sid, cycle_id, analysis, all_executions)
        # Surface the Fix F update count + Fix N failure count
        # on the learning phase summary so operators can see
        # how many smart-exec outcomes landed in the weight
        # store this cycle and how many dropped.
        if isinstance(learning, dict):
            learning["weight_updates"] = weight_updates
            learning["weight_store_update_failures"] = weight_store_update_failures

        # Brain learning loop — learn from this cycle + smart executions.
        # Fix R: aggregate the rich failure_insight /
        # success_insight dicts that learn() returns into a
        # single brain_insights list on the learning phase
        # summary, and report success/failure counts so
        # operators can see the signal in cycle output
        # instead of silently logging it.
        brain_insights: list[dict[str, Any]] = []
        brain_success_count = 0
        brain_failure_count = 0
        try:
            from core.brain.learning_loop import LearningLoop
            brain_loop = LearningLoop()
            cycle_metrics = {
                "insights": cycle_result["phases"]["analysis"]["insights"],
                "actions_proposed": cycle_result["phases"]["decisions"]["proposed"],
                "smart_executed": len(se_results),
                "avg_exec_score": smart_exec_result.get("avg_score", 0) if isinstance(smart_exec_result, dict) else 0,
            }
            brain_learning = brain_loop.learn(
                "cycle", {"store_id": sid, "cycle": self._cycle_count},
                "autonomous_cycle",
                {"status": "complete", "insights": cycle_metrics["insights"],
                 "executions": len(se_results)},
                cycle_metrics,
            )
            learning["brain_learning"] = {
                "score": brain_learning.get("score", 0),
                "success": brain_learning.get("success", False),
            }
            if brain_learning.get("success_insight"):
                brain_insights.append({
                    "type": "success",
                    "action": "autonomous_cycle",
                    **brain_learning["success_insight"],
                })
                brain_success_count += 1
            if brain_learning.get("failure_insight"):
                brain_insights.append({
                    "type": "failure",
                    "action": "autonomous_cycle",
                    **brain_learning["failure_insight"],
                })
                brain_failure_count += 1

            # Learn from each smart execution individually
            for se in se_results:
                action_name = se.get("action_type", "unknown")
                se_learning = brain_loop.learn(
                    category=se.get("action_type", "execution"),
                    input_data={"action": action_name, "mode": se.get("mode", "")},
                    action=action_name,
                    result=se.get("actual_outcome", {}),
                    metrics={"profit": se.get("score", 3.0) - 3.0},
                )
                learning["outcomes_recorded"] = learning.get("outcomes_recorded", 0) + 1
                if se_learning.get("success_insight"):
                    brain_insights.append({
                        "type": "success",
                        "action": action_name,
                        **se_learning["success_insight"],
                    })
                    brain_success_count += 1
                if se_learning.get("failure_insight"):
                    brain_insights.append({
                        "type": "failure",
                        "action": action_name,
                        **se_learning["failure_insight"],
                    })
                    brain_failure_count += 1
        except Exception as exc:
            _record("brain_learning", exc)

        # Surface aggregated insights regardless of whether
        # the try-block above completed — partial failures
        # still yield whatever insights landed before the exception.
        if isinstance(learning, dict):
            learning["brain_insights"] = brain_insights
            learning["brain_success_count"] = brain_success_count
            learning["brain_failure_count"] = brain_failure_count

        cycle_result["phases"]["learning"] = learning

        # Close the goal → cycle → outcome → next selection loop.
        # profit_delta is the smart-exec avg score vs the 3.0
        # "fine" midpoint; weight updates and insights are
        # secondary positive signals.
        try:
            selected = cycle_result["phases"].get("goal", {}).get("selected", "")
            if selected and getattr(self, "_goal_manager", None) is not None:
                avg_score = (
                    smart_exec_result.get("avg_score", 0)
                    if isinstance(smart_exec_result, dict) else 0
                )
                insights = cycle_result["phases"].get("analysis", {}).get("insights", 0)
                weight_update_count = (
                    learning.get("weight_updates", 0)
                    if isinstance(learning, dict) else 0
                )
                self._goal_manager.record_goal_outcome(selected, {
                    "profit_delta": float(avg_score - 3.0) if avg_score else 0.0,
                    "revenue_delta": float(weight_update_count),
                    "health_delta": float(insights) - 1.0,
                })
                if isinstance(learning, dict):
                    learning["goal_effectiveness"] = round(
                        self._goal_manager.get_effectiveness(selected), 3,
                    )
        except Exception as exc:
            _record("goal_outcome_update", exc)

        # Phase 5a: MARKETING AUTOMATION — generate campaigns
        try:
            from execution.marketing.auto_campaign import get_marketing_automation
            mkt = get_marketing_automation()
            mkt_result = mkt.generate_campaigns(
                data.get("products", []),
                data.get("customer_data", []),
                data.get("order_data", []),
                store_id=sid,
            )
            cycle_result["phases"]["marketing_auto"] = {
                "campaigns": mkt_result.get("total", 0),
                "types": mkt_result.get("by_type", {}),
                "estimated_revenue": mkt_result.get("estimated_revenue", 0),
            }
        except Exception as exc:
            _record("marketing_automation", exc)

        # Phase 5a2: STRATEGY PLANNER — long-term plans
        if self._cycle_count % 5 == 1:  # Every 5 cycles
            try:
                from core.brain.strategy_planner import get_strategy_planner
                sp = get_strategy_planner()
                plan = sp.plan(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                    store_id=sid,
                )
                cycle_result["phases"]["strategy"] = {
                    "strategies": plan.get("total", 0),
                    "priority": plan.get("priority_order", []),
                    "intelligence": plan.get("intelligence_used", {}),
                }
            except Exception as exc:
                _record("strategy_planner", exc)

        # Phase 5b: DOMAIN CAPTURE — fill all 12 data domains
        if hasattr(self, '_unified_memory') and self._unified_memory:
            try:
                domain_stats = self._capture_all_domains(
                    sid, data, analysis, cycle_result, brain_decisions,
                    smart_exec_result,
                )
                cycle_result["phases"]["domain_capture"] = domain_stats
            except Exception as exc:
                _record("domain_capture", exc)

        # Phase 6: REPORT — Generate cycle summary
        elapsed = time.monotonic() - start
        cycle_result["duration_s"] = round(elapsed, 2)
        cycle_result["status"] = "complete"

        # Phase 6b: SELF-IMPROVE — review cycle and learn from mistakes
        try:
            from core.ai.self_improver import SelfImprover
            improver = SelfImprover()
            review = improver.review_cycle(cycle_result)
            cycle_result["phases"]["self_improvement"] = review
        except Exception as exc:
            _record("self_improvement_review", exc)

        # Phase 6c: MAINTENANCE — prune old data, cleanup
        if self._cycle_count % 10 == 0:  # Every 10 cycles
            try:
                from core.memory.unified_memory import get_unified_memory
                from core.data.architecture import get_data_architecture
                mi = get_unified_memory().get_memory_intelligence()
                da = get_data_architecture()
                pruned = mi.prune_unused(days=30)
                expired = da.cleanup_expired()
                if pruned or expired:
                    logger.info("Maintenance: pruned %d memories, %d expired records", pruned, expired)
            except Exception as exc:
                _record("memory_maintenance", exc)

        # Phase 7: RULE HEALTH CHECK — monitor rule effectiveness
        try:
            from core.brain.rule_health import get_rule_health_checker
            rhc = get_rule_health_checker()
            health = rhc.check()
            cycle_result["phases"]["rule_health"] = {
                "total_rules": health.get("total_rules", 0),
                "healthy": health.get("healthy", 0),
                "zero_success": len(health.get("zero_success", [])),
                "health_score": health.get("health_score", 0),
                "recommendations": health.get("recommendations", []),
            }
        except Exception as exc:
            _record("rule_health", exc)

        # Phase 7b: EXECUTION PROMOTION — track and promote modes
        try:
            from execution.promoter import get_execution_promoter
            promoter = get_execution_promoter()
            se_results_list = smart_exec_result.get("results", []) if isinstance(smart_exec_result, dict) else []
            for se in se_results_list:
                promoter.record(se.get("action_type", ""), se.get("mode", "simulate"), se.get("score", 3.0))
            # Check for promotions
            promotion_recs = {}
            for se in se_results_list:
                at = se.get("action_type", "")
                if at and at not in promotion_recs:
                    rec = promoter.recommend_mode(at, default_mode="simulate")
                    if rec.get("mode") != "simulate":
                        promotion_recs[at] = rec
            if promotion_recs:
                cycle_result["phases"]["execution_promotion"] = promotion_recs
        except Exception as exc:
            _record("execution_promotion", exc)

        # Phase 7c: STRATEGY EXPANSION — every 5 cycles
        if self._cycle_count % 5 == 0:
            try:
                from core.brain.strategy_expander import get_strategy_expander
                expander = get_strategy_expander()
                expansion = expander.expand()
                if expansion.get("expanded", 0) > 0:
                    cycle_result["phases"]["strategy_expansion"] = {
                        "expanded": expansion.get("expanded", 0),
                        "coverage": expansion.get("categories_covered_after", 0),
                    }
            except Exception as exc:
                _record("strategy_expansion", exc)

        # Phase 8: PRODUCT SCORING — AI-learned product ranking
        try:
            from models.ml.product_scorer import get_product_scorer
            ps = get_product_scorer()
            product_scores = ps.score_all(data.get("products", []))
            cycle_result["phases"]["product_scoring"] = {
                "scored": len(product_scores),
                "top_product": product_scores[0]["name"] if product_scores else "?",
                "top_score": product_scores[0]["total_score"] if product_scores else 0,
                "grade_A": sum(1 for s in product_scores if s["grade"] == "A"),
                "grade_D": sum(1 for s in product_scores if s["grade"] == "D"),
            }
        except Exception as exc:
            _record("product_scoring", exc)

        # Phase 8b: COMPETITIVE INTELLIGENCE — deep market analysis
        try:
            from core.brain.competitive_intel import get_competitive_intelligence
            ci = get_competitive_intelligence()
            comp_intel = ci.analyze(
                data.get("products", []),
                data.get("competitor_data", []),
            )
            cycle_result["phases"]["competitive_intel"] = {
                "position": comp_intel.get("market_position", {}).get("position", "unknown"),
                "advantages": len(comp_intel.get("advantages", [])),
                "vulnerabilities": len(comp_intel.get("vulnerabilities", [])),
                "recommendations": comp_intel.get("recommendations", [])[:2],
            }
        except Exception as exc:
            _record("competitive_intel", exc)

        # Phase 8c: ALERTS — check for important events
        try:
            from core.system.alerts import get_alert_system
            alerts = get_alert_system()
            cycle_alerts = alerts.check_cycle(cycle_result)
            if cycle_alerts:
                cycle_result["phases"]["alerts"] = {
                    "count": len(cycle_alerts),
                    "critical": sum(1 for a in cycle_alerts if a["severity"] == "critical"),
                    "warnings": sum(1 for a in cycle_alerts if a["severity"] == "warning"),
                    "messages": [a["message"] for a in cycle_alerts[:3]],
                }
        except Exception as exc:
            _record("alerts", exc)

        # Phase 8d: PRODUCT PERFORMANCE — track over time
        try:
            from core.system.product_performance import get_product_performance
            pp = get_product_performance()
            pp.record(data.get("products", []),
                      product_scores if 'product_scores' in dir() else None)
        except Exception as exc:
            _record("product_performance", exc)

        # Phase 8e: TREND ANALYSIS — cross-cycle trends
        try:
            from core.system.trend_analyzer import get_trend_analyzer
            ta = get_trend_analyzer()
            ta.record_cycle(cycle_result)
            if self._cycle_count >= 3:
                trends = ta.analyze()
                cycle_result["phases"]["trends"] = {
                    "cycles": trends.get("cycles_analyzed", 0),
                    "health": trends.get("health_trend", "unknown"),
                    "details": trends.get("trends", {}),
                }
        except Exception as exc:
            _record("trend_analysis", exc)

        # Phase 8f: CHAIN OF THOUGHT — structured reasoning on top problem
        try:
            from core.brain.reasoning_chain import get_chain_of_thought
            cot = get_chain_of_thought()
            brain_phase = cycle_result.get("phases", {}).get("brain", {})
            top_problem = brain_phase.get("top_action", "optimize_store")
            reasoning = cot.reason(
                "Should we {} for this store?".format(top_problem),
                {"products": data.get("products", [])[:5],
                 "orders": data.get("order_data", []),
                 "health_score": brain_phase.get("health_score", 0)},
            )
            cycle_result["phases"]["chain_of_thought"] = {
                "question": reasoning.get("question", "")[:60],
                "answer": reasoning.get("answer", "")[:60],
                "confidence": reasoning.get("confidence", 0),
                "steps": reasoning.get("reasoning_length", 0),
            }
        except Exception as exc:
            _record("chain_of_thought", exc)

        # Phase 8g: FULFILLMENT — check order fulfillment status
        try:
            from execution.fulfillment.auto_fulfill import get_fulfillment
            ff = get_fulfillment()
            ff_result = ff.process_orders(
                data.get("order_data", []),
                data.get("products", []),
            )
            if ff_result.get("total_orders", 0) > 0:
                # Pre-fix the fulfillment summary dropped the
                # ``shipping_rate_source`` field the migrated
                # ``auto_fulfill`` adds to every per-order
                # result, so the operator couldn't see whether
                # shipping rates came from a real carrier
                # adapter or fell back to the placeholder.
                # Aggregate the per-order sources into a count
                # map and surface it here.
                rate_sources: dict[str, int] = {}
                for r in ff_result.get("results", []):
                    if not isinstance(r, dict):
                        continue
                    src = r.get("shipping_rate_source", "")
                    if src:
                        rate_sources[src] = rate_sources.get(src, 0) + 1
                cycle_result["phases"]["fulfillment"] = {
                    "total": ff_result.get("total_orders", 0),
                    "fulfillable": ff_result.get("fulfillable", 0),
                    "blocked": ff_result.get("blocked", 0),
                    "shipping_rate_sources": rate_sources,
                }
        except Exception as exc:
            _record("fulfillment", exc)

        # Phase 8h: MULTI-STORE — share learnings
        try:
            from core.brain.multi_store_brain import get_multi_store
            ms = get_multi_store()
            ms.register_store(sid)
            shared = ms.share_learning(sid)
            if shared.get("shareable_rules", 0) > 0:
                cycle_result["phases"]["multi_store"] = {
                    "shareable_rules": shared.get("shareable_rules", 0),
                    "shareable_strategies": shared.get("shareable_strategies", 0),
                }
        except Exception as exc:
            _record("multi_store", exc)

        # Phase 8i: DASHBOARD — generate dashboard snapshot
        try:
            from core.system.dashboard import get_dashboard
            dash = get_dashboard()
            cycle_result["_dashboard"] = dash.generate(cycle_result)
        except Exception as exc:
            _record("dashboard_generate", exc)

        # Phase 8j: LIVE EXECUTION — execute safe actions on Shopify
        try:
            from execution.live_executor import get_live_executor
            le = get_live_executor()
            # Only execute safe actions if we have credentials
            creds = {}
            if self._store_manager:
                creds = self._store_manager.get_credentials(sid)
            if creds.get("api_key"):
                # Find products without descriptions to update
                safe_actions = []
                for p in data.get("products", [])[:2]:
                    pid = str(p.get("id", ""))
                    desc = str(p.get("body_html", p.get("description", ""))).strip()
                    if pid and not desc:
                        safe_actions.append({
                            "type": "update_description",
                            "product_id": pid,
                            "description": "Quality {} product. Great value at ${}.".format(
                                p.get("product_type", ""), p.get("price", "")),
                        })
                live_results = []
                for action in safe_actions[:1]:  # Max 1 per cycle for safety
                    r = le.execute(action.get("type", ""), sid, action, creds)
                    live_results.append(r)
                if live_results:
                    cycle_result["phases"]["live_execution"] = {
                        "actions": len(live_results),
                        "success": sum(1 for r in live_results if r.get("status") == "success"),
                    }
        except Exception as exc:
            _record("live_execution", exc)

        # Phase 8k: CONTINUOUS OPTIMIZATION — auto-fix store issues
        try:
            from execution.continuous_optimizer import get_continuous_optimizer
            co = get_continuous_optimizer()
            creds = {}
            if self._store_manager:
                creds = self._store_manager.get_credentials(sid)
            co_result = co.optimize(
                data.get("products", []),
                data.get("customer_data", []),
                shop_url=creds.get("shop_url", ""),
                token=creds.get("api_key", ""),
                store_id=sid,
            )
            if co_result.get("fixes_applied", 0) > 0:
                cycle_result["phases"]["continuous_optimization"] = co_result
        except Exception as exc:
            _record("continuous_optimizer", exc)

        # Phase 8k2: REVENUE STRATEGY — generate revenue plan
        if self._cycle_count % 10 == 1:
            try:
                from core.brain.revenue_strategy import get_revenue_strategy
                rs = get_revenue_strategy()
                rev_plan = rs.create_plan(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                )
                cycle_result["phases"]["revenue_strategy"] = {
                    "phase": rev_plan.get("phase", ""),
                    "strategies": len(rev_plan.get("strategies", [])),
                    "immediate_actions": len(rev_plan.get("immediate_actions", [])),
                }
            except Exception as exc:
                _record("revenue_strategy", exc)

        # Phase 8k3: SEO ANALYSIS
        try:
            from core.system.seo_analyzer import get_seo_analyzer
            seo = get_seo_analyzer()
            seo_result = seo.analyze_all(data.get("products", [])[:5])
            cycle_result["phases"]["seo_analysis"] = {
                "avg_score": seo_result.get("avg_seo_score", 0),
                "grades": seo_result.get("grade_distribution", {}),
                "top_issues": seo_result.get("top_issues", [])[:3],
            }
        except Exception as exc:
            _record("seo_analysis", exc)

        # Phase 8k4: PROFIT CALCULATOR
        try:
            from core.system.profit_calculator import get_profit_calculator
            pc = get_profit_calculator()
            profit = pc.calculate_store(data.get("products", []), data.get("order_data", []))
            cycle_result["phases"]["profit_analysis"] = {
                "profitable": profit.get("profitable", 0),
                "unprofitable": profit.get("unprofitable", 0),
                "avg_margin": profit.get("avg_margin", 0),
                "needs_attention": len(profit.get("needs_attention", [])),
            }
        except Exception as exc:
            _record("profit_calculator", exc)

        # Phase 8k5: SOCIAL CONTENT — generate posts for top products
        if self._cycle_count % 5 == 1:
            try:
                from execution.content.social_content import get_social_content
                sc = get_social_content()
                social = sc.generate_batch(data.get("products", [])[:3])
                cycle_result["phases"]["social_content"] = {
                    "products": social.get("total_products", 0),
                    "platforms": 4,
                }
            except Exception as exc:
                _record("social_content", exc)

        # Phase 8k6: EMAIL SEQUENCES — build on first cycle
        if self._cycle_count <= 1:
            try:
                from execution.marketing.email_sequences import get_email_builder
                eb = get_email_builder()
                emails = eb.build_all("deguar", "https://deguar.myshopify.com",
                                      data.get("products", [])[:3])
                cycle_result["phases"]["email_sequences"] = {
                    "sequences": emails.get("total_sequences", 0),
                    "total_emails": emails.get("total_emails", 0),
                }
            except Exception as exc:
                _record("email_sequences", exc)

        # Phase 8k7: MODEL WORKERS — AI model tasks on products
        try:
            from core.system.model_workers import get_model_workers
            mw = get_model_workers()
            model_tasks = []
            for p in data.get("products", [])[:3]:
                r = mw.execute_task("analyze_product", {
                    "name": p.get("name", p.get("title", "")),
                    "price": p.get("price", 0),
                    "cost": p.get("cost", 0),
                    "category": p.get("product_type", ""),
                }, store_id=sid)
                model_tasks.append(r)
            if model_tasks:
                cycle_result["phases"]["model_workers"] = {
                    "tasks": len(model_tasks),
                    "roles_used": list(set(t.get("role", "") for t in model_tasks)),
                    "models_used": list(set(t.get("model", "") for t in model_tasks)),
                }
        except Exception as exc:
            _record("model_workers", exc)

        # Phase 8l: TOOL DISCOVERY — check available tools
        if self._cycle_count <= 1:
            try:
                from core.system.tool_orchestrator import get_tool_orchestrator
                to = get_tool_orchestrator()
                disc = to.discover()
                cycle_result["phases"]["tool_discovery"] = {
                    "available": disc.get("available", 0),
                    "total": disc.get("total_tools", 0),
                }
            except Exception as exc:
                _record("tool_discovery", exc)

        # Phase 8m: TIMESERIES — domain trend analysis
        try:
            from core.data.timeseries import get_timeseries
            ts = get_timeseries()
            trends = ts.all_domains(days=1)
            cycle_result["phases"]["timeseries"] = {
                "improving": trends.get("improving", 0),
                "declining": trends.get("declining", 0),
                "stable": trends.get("stable", 0),
            }
        except Exception as exc:
            _record("timeseries", exc)

        # Phase 8n: SIMILARITY SEARCH — find related memories for top decision
        try:
            from core.memory.similarity_search import get_similarity_search
            ss = get_similarity_search()
            products = data.get("products", [])
            if products:
                top_p = products[0]
                features = {"has_price": bool(top_p.get("price")),
                            "margin": (float(top_p.get("price",0)) - float(top_p.get("cost",0))) / max(float(top_p.get("price",1)),1) if top_p.get("cost") else 0}
                similar = ss.search(features, "pricing", limit=3)
                cycle_result["phases"]["similarity_search"] = {
                    "found": len(similar),
                    "top_similarity": similar[0].get("_similarity", 0) if similar else 0,
                }
        except Exception as exc:
            _record("similarity", exc)

        # Phase 8o: CONTENT CALENDAR — plan upcoming content
        if self._cycle_count <= 1:
            try:
                from core.system.content_calendar import get_content_calendar
                cc = get_content_calendar()
                cal = cc.generate_calendar(data.get("products", []), weeks=4)
                cycle_result["phases"]["content_calendar"] = {
                    "weeks": cal.get("weeks", 0),
                    "total_items": cal.get("total_items", 0),
                    "types": cal.get("by_type", {}),
                }
            except Exception as exc:
                _record("content_calendar", exc)

        # Phase 8p: REAL IMAGE FINDER — search for better images
        if self._cycle_count % 10 == 1:
            try:
                from execution.content.real_image_finder import get_real_image_finder
                rif = get_real_image_finder()
                img_result = rif.find_real_images(data.get("products", [])[:3])
                if img_result.get("found", 0) > 0:
                    cycle_result["phases"]["real_images"] = img_result
            except Exception as exc:
                _record("real_images", exc)

        # Phase 9: STRUCTURED LOGGING — log this cycle
        try:
            from core.system.structured_logger import get_structured_logger
            sl = get_structured_logger()
            sl.log_cycle(cycle_result)
        except Exception as exc:
            _record("structured_log", exc)

        # Phase 9b: CYCLE REPORT — human-readable summary
        try:
            from core.system.cycle_reporter import get_cycle_reporter
            reporter = get_cycle_reporter()
            cycle_result["_report"] = reporter.report(cycle_result)
        except Exception as exc:
            _record("cycle_reporter", exc)

        # Phase 9b: NOTIFICATIONS — deliver alerts
        try:
            from core.system.notifications import get_notifications
            notif = get_notifications()
            notif.send_cycle_summary(cycle_result)
        except Exception as exc:
            _record("notifications", exc)

        # Track performance
        if self._performance_tracker:
            self._performance_tracker.record_cycle(cycle_result)

        # Cognitive Mind shadow / primary cycle
        if self._cognitive_mode != "off" and self._cognitive_mind is not None:
            cognitive_report = self._run_cognitive_phase(cycle_result)
            if cognitive_report is not None:
                cycle_result["cognitive"] = cognitive_report

        # Wave 7b (NEW-A): inject synthetic error sources into
        # phase_errors *before* snapshotting into cycle_result so
        # the history and observability reflect the full picture.
        # Previously these blocks ran after the snapshot, leaving
        # cycle_result["phase_errors"] stale.

        # Wave 7c (GAP-15): inject cognitive Mind errors at
        # per-phase granularity when available. Falls back to the
        # old single-blob "cognitive_mind" key for pre-GAP-15 Mind
        # instances that don't report phase_errors.
        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict):
            cog_phases = cog.get("phase_errors")
            if isinstance(cog_phases, dict) and cog_phases:
                for phase_key, err_msg in cog_phases.items():
                    phase_errors[f"cognitive_{phase_key}"] = str(err_msg)
            elif cog.get("error"):
                phase_errors["cognitive_mind"] = str(cog["error"])

        # Wave 7 #2: inject SLA breaches into phase_errors so
        # recurring adapter degradation feeds the reflection
        # synthesizer and can eventually promote SOFT block rules.
        self._inject_sla_breaches(phase_errors)

        # Surface the per-cycle error ledger. ``phase_errors``
        # was populated by every phase's ``_record`` call-site
        # (plus Mind + SLA injections above) so operators can see
        # which subsystems failed even when the cycle overall
        # completed. Empty dict means every phase ran clean;
        # presence of keys means something degraded.
        if phase_errors:
            cycle_result["phase_errors"] = dict(phase_errors)
            cycle_result["phase_error_count"] = len(phase_errors)
            logger.warning(
                "Cycle %s had %d phase failures: %s",
                cycle_id, len(phase_errors),
                ", ".join(sorted(phase_errors.keys())),
            )
        else:
            cycle_result["phase_errors"] = {}
            cycle_result["phase_error_count"] = 0

        # Save to history
        self._cycle_history.append(cycle_result)
        if len(self._cycle_history) > self._max_history:
            self._cycle_history = self._cycle_history[-self._max_history:]

        logger.info("Cycle %s complete in %.1fs: %d insights, %d actions",
                     cycle_id, elapsed,
                     cycle_result["phases"]["analysis"]["insights"],
                     cycle_result["phases"]["decisions"]["proposed"])

        # Obsidian vault: log cycle outcome as a vault note so
        # the operator can see the decision history in graph view.
        # Best-effort — never blocks the cycle.
        try:
            self._log_cycle_to_vault(cycle_result, phase_errors)
        except Exception as exc:  # noqa: BLE001
            _record("vault_cycle_log", exc)

        # Adapter-powered side effects: analytics events, CRM
        # upserts, helpdesk alerts, automation webhooks. Each hook
        # is a no-op when the relevant adapter isn't configured,
        # so operators opt in by just setting the API key. The
        # whole bundle is wrapped so a hook failure can never
        # break the cycle loop.
        try:
            from core.autonomous.adapter_hooks import run_post_cycle_hooks
            hook_summary = run_post_cycle_hooks(
                self._adapter_router, cycle_result, data, phase_errors,
            )
            if hook_summary.get("enabled"):
                cycle_result["phases"]["adapter_hooks"] = hook_summary
        except Exception as exc:  # noqa: BLE001
            _record("adapter_hooks", exc)

        # Upgrade 2: auto-replay coordinator scan. Classify any
        # dead-letter entries whose adapters have since recovered
        # (breaker closed, no strong route-weight penalty) as
        # READY — the coordinator's registered callback (if any)
        # performs the replay. We surface the counts regardless
        # so operators can see "N entries could be retried now"
        # without installing the callback.
        try:
            from core.adapters.auto_replay import (
                get_auto_replay_coordinator,
            )
            replay_report = get_auto_replay_coordinator().scan()
            cycle_result["phases"]["auto_replay"] = {
                "ready": len(replay_report.ready),
                "degraded": len(replay_report.degraded),
                "replayed_already": len(replay_report.replayed),
                "skipped_recent": replay_report.skipped_recent,
                "callback_invocations": replay_report.callback_invocations,
                "callback_failures": replay_report.callback_failures,
            }
        except Exception as exc:  # noqa: BLE001
            _record("auto_replay_scan", exc)

        # Option E: collect adapter-layer reliability signals
        # (health / dead-letter / cost) and embed them on
        # ``cycle_result["phases"]["reliability"]``. If any signal
        # crosses a threshold, append a ``reliability_alert`` entry
        # to ``phase_errors`` so the reflection synthesizer can
        # mine recurring adapter-degradation patterns the same way
        # it already mines phase exceptions.
        #
        # Every call inside ``collect_reliability_signal`` is
        # wrapped in its own try/except — a missing SLA row or
        # breaker snapshot can never break the cycle. The outer
        # try here is belt-and-braces.
        try:
            from core.autonomous.reliability import (
                collect_reliability_signal,
            )
            signal = collect_reliability_signal()
            cycle_result["phases"]["reliability"] = {
                "health_totals": signal["health"].get("totals", {}),
                "unhealthy_adapters": signal["health"].get("unhealthy", []),
                "degraded_adapters": signal["health"].get("degraded", []),
                "deadletter_total": signal["deadletter"].get(
                    "total_records", 0,
                ),
                "deadletter_new_since_last": signal["deadletter"].get(
                    "new_since_last", 0,
                ),
                "cost_total_usd": signal["cost"].get("total_usd", 0.0),
                "cost_delta_usd": signal["cost"].get("delta_usd", 0.0),
                "cost_top_caller": signal["cost"].get("top_caller", ""),
                "alerts": list(signal.get("alerts", [])),
            }
            for idx, alert in enumerate(signal.get("alerts", [])):
                # Keep keys unique within ``phase_errors`` so
                # reflection treats each one as its own signal.
                key = (
                    f"reliability_alert_{idx}" if idx
                    else "reliability_alert"
                )
                phase_errors[key] = alert
                cycle_result["phase_errors"][key] = alert
            if signal.get("alerts"):
                cycle_result["phase_error_count"] = len(
                    cycle_result["phase_errors"]
                )
                logger.warning(
                    "Reliability alerts for cycle %s: %s",
                    cycle_id, "; ".join(signal["alerts"]),
                )
        except Exception as exc:  # noqa: BLE001
            _record("reliability_signal", exc)

        # Wave 2 #5: post-tick reflection hook. Mines the cycle's
        # error ledger for recurring patterns and, when confidence
        # is high enough, promotes them to SOFT rules on the
        # policy store. Guarded so a missing optional dep or a
        # synthesizer exception never breaks the cycle loop.
        try:
            self._run_reflection_hook(cycle_result, phase_errors)
        except Exception as exc:  # noqa: BLE001
            # Wave 7 #4: the hook's own failures are recorded in
            # phase_errors so they show up in observability and
            # can be mined by future reflection runs. Also patch
            # the already-snapshotted cycle_result so history is
            # consistent.
            phase_errors["reflection_hook"] = (
                f"{type(exc).__name__}: {exc}"
            )
            cycle_result["phase_errors"]["reflection_hook"] = (
                phase_errors["reflection_hook"]
            )
            cycle_result["phase_error_count"] = len(
                cycle_result["phase_errors"]
            )
            logger.warning("reflection hook failed: %s", exc)

        return cycle_result

    # Wave 6 #1: default rolling-window size for the cross-cycle
    # error buffer. Set as a class attribute so tests can shrink it
    # by assigning ``controller._reflection_buffer_max = N`` before
    # running ticks. 256 is comfortably larger than typical
    # phase-error fan-out but still flat in memory.
    # Wave 7 #8 (GAP-12): env-var configurable.
    _REFLECTION_BUFFER_MAX = int(
        os.environ.get("SHOPAI_REFLECTION_BUFFER_MAX", "256"),
    )

    # Wave 6 #10: throttled auto-decay of stale learned SOFT rules.
    # The reflection hook calls ``decay_stale_rules`` at most once
    # per ``_REFLECTION_DECAY_INTERVAL_SEC`` and retires any learned
    # rule whose last activity is older than
    # ``_REFLECTION_DECAY_MAX_IDLE_SEC``. Defaults: every 1h check,
    # 30-day idle window. Both can be overridden per-instance by
    # tests or by the env vars ``SHOPAI_REFLECTION_DECAY_INTERVAL_SEC``
    # and ``SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC``.
    _REFLECTION_DECAY_INTERVAL_SEC = 3600.0
    _REFLECTION_DECAY_MAX_IDLE_SEC = 30.0 * 24.0 * 3600.0

    def _run_reflection_hook(
        self,
        cycle_result: dict[str, Any],
        phase_errors: dict[str, str],
    ) -> None:
        """Feed this cycle's errors to the reflection synthesizer.

        Wave 2 #5 created this hook; Wave 6 #1 closes a real
        learning gap inside it: the original implementation only
        handed the synthesizer the CURRENT cycle's ``phase_errors``
        dict (typically 0-3 records), so patterns rarely crossed
        the ``min_occurrences`` floor. Any recurring failure that
        hit one phase per tick would never accumulate.

        This version keeps a bounded rolling buffer of all recent
        error records across cycles and mines the full buffer on
        every tick. The synthesizer's internal ``_promoted``
        ledger keeps duplicate promotions out, so running over a
        growing buffer is cheap and idempotent.

        The hook is a no-op when:

        * the cycle had no phase errors (nothing to learn from), or
        * ``core.reflection`` cannot be imported (optional package),
          or
        * the synthesizer run raises — caught and logged upstream.
        """
        if not phase_errors:
            return
        # Defer import so controller startup doesn't eagerly load
        # the synthesizer package if the controller runs in a
        # stripped-down deployment that doesn't care about
        # reflection.
        from collections import deque
        from core.memory.quality_engine import MemoryRecord
        from core.reflection.synthesizer import (
            ReflectionSynthesizer,
            get_default_synthesizer,
        )

        # Wave 6 #19d: double-checked locking — the fast path
        # (already initialised) skips the lock entirely. getattr
        # guards the lock lookup for bare instances created via
        # __new__ in test harnesses that bypass __init__.
        if self._reflection_synth is None or self._error_buffer is None:
            init_lock = getattr(self, "_reflection_init_lock", None)
            if init_lock is None:
                init_lock = threading.Lock()
                self._reflection_init_lock = init_lock
            with init_lock:
                if self._reflection_synth is None:
                    try:
                        self._reflection_synth = get_default_synthesizer()
                    except Exception:  # noqa: BLE001
                        self._reflection_synth = ReflectionSynthesizer()
                if self._error_buffer is None:
                    maxlen = getattr(
                        self, "_reflection_buffer_max",
                        self._REFLECTION_BUFFER_MAX,
                    )
                    self._error_buffer = deque(maxlen=maxlen)

        now = time.time()
        new_records = [
            MemoryRecord(
                kind="error",
                quality=0.6,
                confidence=0.7,
                success_rate=0.0,
                usage=1,
                created_at=now,
                payload={"phase": phase, "message": message},
            )
            for phase, message in phase_errors.items()
        ]
        self._error_buffer.extend(new_records)
        # Mine over the full rolling window, not just this tick's
        # slice — that's the whole point of Wave 6 #1.
        report = self._reflection_synth.run(list(self._error_buffer))
        if report.patterns_promoted:
            cycle_result.setdefault("reflection", {})
            cycle_result["reflection"] = report.as_dict()
            logger.info(
                "Reflection hook promoted %d SOFT rules from cycle %s "
                "(buffer=%d records)",
                report.patterns_promoted, cycle_result.get("cycle_id"),
                len(self._error_buffer),
            )
            # Upgrade 1: close the loop — feed promoted patterns
            # back into the router's learned-weight ledger. A
            # pattern that names ``adapter`` + ``capability`` is
            # exactly the signal "this pair is flakier than its
            # declared priority implies; prefer alternatives".
            try:
                from core.adapters.route_weights import (
                    get_route_weight_ledger,
                )
                applied = get_route_weight_ledger().apply_reflection_report(
                    report,
                )
                if applied:
                    cycle_result["reflection"]["route_weight_penalties"] = (
                        applied
                    )
                    logger.info(
                        "Route-weight ledger: %d (adapter, capability) "
                        "pair(s) penalized from cycle %s",
                        applied, cycle_result.get("cycle_id"),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "route_weight ledger update skipped: %s", exc,
                )

        # Wave 6 #10: throttled auto-decay of stale learned rules.
        # We call decay at most once per ``_REFLECTION_DECAY_INTERVAL_SEC``
        # so the cost stays flat even on high-frequency cycles.
        retired = self._maybe_run_reflection_decay(now)
        if retired:
            cycle_result.setdefault("reflection", {})
            cycle_result["reflection"].setdefault("retired_rules", retired)
            logger.info(
                "Reflection: retired %d stale learned rule(s) in cycle %s",
                len(retired), cycle_result.get("cycle_id"),
            )

        # Obsidian vault auto-export: persist promoted patterns and
        # learned knowledge as markdown notes in the vault. Only runs
        # when OBSIDIAN_VAULT_PATH is configured. Best-effort — a
        # missing adapter or write failure never breaks the cycle.
        self._maybe_export_to_vault(report)

        # Wave 7 / Option P: mine the chat-feedback notes written by
        # the dashboard's Option H handler and promote recurring
        # complaint themes into ``ShopAI/Learned/lessons/``. Same
        # best-effort contract as ``_maybe_export_to_vault`` — any
        # failure is logged and swallowed.
        self._maybe_learn_from_feedback(cycle_result)

    # ── Obsidian vault auto-export ──────────────────────────────

    def _maybe_export_to_vault(self, report: Any) -> None:
        """Export learned knowledge to Obsidian vault if configured.

        Called at the end of ``_run_reflection_hook``. Exports run
        unconditionally on every reflection cycle that PROMOTED
        patterns, plus an opportunistic hourly sweep so any memory
        record marked ``source="learned"`` reaches the vault even
        if reflection found nothing new that cycle — previously we
        gated export strictly on ``patterns_promoted > 0``, which
        meant out-of-band ingests (manual memory loads, feedback
        learner lessons) stayed invisible to the graph until the
        next promotion.

        Best-effort: a missing adapter, unconfigured vault path, or
        write failure is silently logged — never breaks the cycle.
        """
        promoted = int(getattr(report, "patterns_promoted", 0) or 0)
        # Thread-safe check-and-reserve: the lock is held only long
        # enough to decide whether THIS cycle is the one that runs
        # the export (and to bump _last_vault_export_ts so any
        # racing cycle sees the updated timestamp). The slow
        # bridge.export_knowledge() call happens OUTSIDE the lock.
        #
        # Tests build a bare controller via ``__new__`` to exercise
        # just the reflection path, skipping ``__init__``. Fall
        # back to sensible defaults so the vault hook stays a
        # no-op instead of crashing the reflection path.
        lock = getattr(self, "_vault_export_lock", None)
        if lock is None:
            import threading
            lock = threading.Lock()
            self._vault_export_lock = lock
        last_ts = float(getattr(self, "_last_vault_export_ts", 0.0) or 0.0)
        interval = float(
            getattr(self, "_vault_min_export_interval_sec", 3600.0) or 3600.0
        )
        with lock:
            now = time.time()
            elapsed = now - last_ts
            due_for_sweep = elapsed >= interval
            if promoted == 0 and not due_for_sweep:
                return
            self._last_vault_export_ts = now
        try:
            from core.adapters.config import get_config
            vault_path = get_config().get("obsidian_vault_path")
            if not vault_path:
                return
            from core.adapters.obsidian.memory_bridge import VaultMemoryBridge
            from core.memory.unified_memory import get_unified_memory
            bridge = VaultMemoryBridge(vault_path)
            result = bridge.export_knowledge(get_unified_memory(), limit=10)
            if result.get("exported", 0):
                logger.info(
                    "Vault auto-export: %d notes written "
                    "(promoted=%d, sweep=%s)",
                    result["exported"], promoted,
                    "yes" if due_for_sweep else "no",
                )
        except Exception as exc:  # noqa: BLE001
            # Promoted from debug → warning so operators see export
            # failures at default log config. The vault-unconfigured
            # path returns early inside the try body, so reaching
            # here always means a real error (missing bridge module,
            # write permission, adapter crash).
            logger.warning("Vault auto-export skipped: %s", exc)

    def _maybe_learn_from_feedback(self, cycle_result: dict[str, Any]) -> None:
        """Promote recurring chat-feedback complaints into lesson notes.

        Reads ``vault/ShopAI/Feedback/*.md``, clusters down-rated notes
        by word-frequency, and writes one lesson per recurring theme
        to ``vault/ShopAI/Learned/lessons/``. The assistant can then
        pull relevant lessons back into its system context on the
        next turn (Option P phase 3).

        Best-effort: a missing vault, unreadable note, or write
        failure is logged and swallowed so feedback learning never
        breaks the autonomous cycle.
        """
        try:
            from core.adapters.config import get_config
            vault_path = get_config().get("obsidian_vault_path")
            if not vault_path:
                return
            from core.learning.feedback_learner import learn_from_feedback
            report = learn_from_feedback(vault_path)
            if report.lessons_written or report.themes_found:
                cycle_result.setdefault("reflection", {})
                cycle_result["reflection"]["feedback_learning"] = report.as_dict()
                logger.info(
                    "Feedback learner: %d lesson(s) written from "
                    "%d down-rated note(s) across %d theme(s)",
                    report.lessons_written, report.down_rated,
                    report.themes_found,
                )
        except Exception as exc:  # noqa: BLE001
            # Promoted from debug → warning: learner failures were
            # invisible at default log level so operators never knew
            # their feedback wasn't being mined into lessons. The
            # vault-unconfigured case returns early, so this branch
            # only fires on real learner failures.
            logger.warning("Feedback learning skipped: %s", exc)

    def _log_cycle_to_vault(
        self,
        cycle_result: dict[str, Any],
        phase_errors: dict[str, str],
    ) -> None:
        """Write a Win or Error note to the Obsidian vault after a cycle.

        Determines outcome from ``phase_errors`` and key metrics in
        ``cycle_result``, then writes a markdown note to either
        ``Wins/`` or ``Errors/`` so the operator can browse the
        decision history in Obsidian's graph view.

        Best-effort: called inside a try/except in ``run_cycle``,
        so failures here never break the autonomous loop.
        """
        from core.adapters.config import get_config

        vault_path = get_config().get("obsidian_vault_path")
        if not vault_path:
            return

        from pathlib import Path

        vault = Path(vault_path)
        if not vault.is_dir():
            return

        from core.adapters.obsidian.parser import write_note

        cycle_id = cycle_result.get("cycle_id", "unknown")
        store_id = cycle_result.get("store_id", "")
        duration = cycle_result.get("duration_s", 0)
        insights = (
            cycle_result.get("phases", {})
            .get("analysis", {})
            .get("insights", 0)
        )
        proposed = (
            cycle_result.get("phases", {})
            .get("decisions", {})
            .get("proposed", 0)
        )
        error_count = cycle_result.get("phase_error_count", 0)

        # Decide Win vs Error: if >25% of phases failed, it's an error.
        total_phases = max(len(cycle_result.get("phases", {})), 1)
        is_error = error_count > 0 and (error_count / total_phases) > 0.25

        if is_error:
            folder = "Errors"
            title = f"Cycle Error {cycle_id}"
            tags = ["error", "cycle", "auto"]
            error_lines = "\n".join(
                f"- **{phase}**: {msg}"
                for phase, msg in phase_errors.items()
            )
            body = (
                f"# {title}\n\n"
                f"## Тоймлол\n\n"
                f"Store: `{store_id}` | Duration: {duration}s | "
                f"Errors: {error_count}/{total_phases} phases\n\n"
                f"## Алдаанууд\n\n{error_lines}\n\n"
                f"## Контекст\n\n"
                f"- Insights: {insights}\n"
                f"- Actions proposed: {proposed}\n\n"
                f"## Холбоотой\n\n"
                f"- [[ShopAI Architecture]]\n"
                f"- [[Example Error Pattern]]\n"
            )
        else:
            folder = "Wins"
            title = f"Cycle Win {cycle_id}"
            tags = ["win", "cycle", "auto"]
            body = (
                f"# {title}\n\n"
                f"## Тоймлол\n\n"
                f"Store: `{store_id}` | Duration: {duration}s | "
                f"Errors: {error_count}\n\n"
                f"## Үр дүн\n\n"
                f"- Insights: {insights}\n"
                f"- Actions proposed: {proposed}\n"
            )
            # Add learning summary if reflection ran
            reflection = cycle_result.get("reflection", {})
            if reflection:
                promoted = reflection.get("patterns_promoted", 0)
                body += f"- Patterns promoted: {promoted}\n"
            body += (
                f"\n## Холбоотой\n\n"
                f"- [[ShopAI Architecture]]\n"
                f"- [[Obsidian Integration Complete]]\n"
            )

        frontmatter = {
            "title": title,
            "tags": tags,
            "date": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "cycle_id": cycle_id,
            "store_id": store_id,
            "phase_error_count": error_count,
        }

        write_note(vault, title, body, frontmatter=frontmatter, folder=folder)
        logger.info("Vault: logged %s to %s/", title, folder)

        # Additional Decisions/ note when the cycle actually
        # proposed or executed actions. The brain picks an action
        # each tick; the operator benefits from seeing those
        # decisions chained together in the graph view, separate
        # from the Win/Error outcome split.
        self._log_decision_to_vault(vault, cycle_result)

    def _log_decision_to_vault(
        self,
        vault: Any,
        cycle_result: dict[str, Any],
    ) -> None:
        """Write a markdown note to ``Decisions/`` for the cycle's
        top decision, if one exists. Best-effort.

        Creating a separate note per cycle would overwhelm the
        vault, so we only write when the brain committed to an
        action (``top_action`` or non-empty proposed list) AND
        skip if a note with the same title already exists today
        (idempotency across repeated cycles with identical state).
        """
        try:
            from core.adapters.obsidian.parser import write_note
            phases = cycle_result.get("phases", {}) or {}
            brain = phases.get("brain", {}) or {}
            decisions_phase = phases.get("decisions", {}) or {}
            top_action = brain.get("top_action", "") or ""
            if not top_action:
                brain_decisions = cycle_result.get("_brain_decisions") or []
                if brain_decisions and isinstance(brain_decisions[0], dict):
                    top_action = brain_decisions[0].get("action", "") or ""
            proposed = decisions_phase.get("proposed", 0)
            if not top_action or proposed == 0:
                return

            cycle_id = cycle_result.get("cycle_id", "unknown")
            store_id = cycle_result.get("store_id", "")
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

            # Deduplicate same-action same-day so we don't write
            # a Decision note for every tick that re-picks the
            # identical action.
            from pathlib import Path
            target_file = (
                Path(vault) / "Decisions"
                / f"{date_str} - {top_action}.md"
            )
            if target_file.exists():
                return

            title = f"{date_str} - {top_action}"
            body = (
                f"# {title}\n\n"
                f"## Шийдвэр\n\n"
                f"Brain сонгосон үйлдэл: **{top_action}**\n\n"
                f"## Контекст\n\n"
                f"- Store: `{store_id}`\n"
                f"- Cycle: `{cycle_id}`\n"
                f"- Actions proposed: {proposed}\n"
                f"- Health score: {brain.get('health_score', 'n/a')}\n"
                f"- Confidence: {brain.get('confidence', 'n/a')}\n\n"
                f"## Холбоотой\n\n"
                f"- [[ShopAI Architecture]]\n"
                f"- [[Cycle Win {cycle_id}]]\n"
            )
            frontmatter = {
                "title": title,
                "tags": ["decision", "auto", top_action.replace(" ", "_")],
                "date": date_str,
                "cycle_id": cycle_id,
                "store_id": store_id,
                "action": top_action,
                "status": "proposed",
            }
            write_note(
                vault, title, body,
                frontmatter=frontmatter, folder="Decisions",
            )
            logger.info("Vault: logged decision %s to Decisions/", title)
        except Exception as exc:  # noqa: BLE001
            # Promoted from debug → warning so decision-log failures
            # (e.g. read-only vault, write-permission error, bad
            # frontmatter) surface at default log level instead of
            # vanishing. Early-returns above handle "no top action"
            # and "already logged today" so this branch only fires
            # on a real write failure.
            logger.warning("Vault decision logging skipped: %s", exc)

    # ── Wave 7c (GAP-4): standalone error ingestion ────────────

    def record_failure(
        self,
        subsystem: str,
        message: str,
        *,
        quality: float = 0.6,
        confidence: float = 0.7,
    ) -> None:
        """Record a standalone failure into the reflection buffer.

        This allows subsystems outside the cycle loop to feed
        errors into the reflection synthesizer's mining pipeline.
        The next ``run_cycle`` call will pick them up automatically
        because the synthesizer mines the full rolling buffer.

        Fail-soft: a missing buffer or import error is logged and
        silently swallowed — callers should never need to guard
        against this method raising.
        """
        try:
            from core.memory.quality_engine import MemoryRecord

            # Ensure the buffer exists (same lazy init as the hook).
            if self._error_buffer is None:
                from collections import deque

                init_lock = getattr(self, "_reflection_init_lock", None)
                if init_lock is None:
                    init_lock = threading.Lock()
                    self._reflection_init_lock = init_lock
                with init_lock:
                    if self._error_buffer is None:
                        maxlen = getattr(
                            self, "_reflection_buffer_max",
                            self._REFLECTION_BUFFER_MAX,
                        )
                        self._error_buffer = deque(maxlen=maxlen)

            record = MemoryRecord(
                kind="error",
                quality=quality,
                confidence=confidence,
                success_rate=0.0,
                usage=1,
                created_at=time.time(),
                payload={
                    "phase": subsystem,
                    "message": message,
                    "source": "record_failure",
                },
            )
            self._error_buffer.append(record)
            logger.debug(
                "record_failure: buffered error from %s (%d in buffer)",
                subsystem, len(self._error_buffer),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("record_failure failed: %s", exc)

    def _maybe_run_reflection_decay(self, now: float) -> list[str]:
        """Call ``synth.decay_stale_rules`` if the throttle interval
        has elapsed.

        Returns the list of retired signatures (empty if the call
        was skipped or no rules were stale). Fails soft — any
        exception in the decay path degrades to an empty list so
        the reflection hook stays healthy.
        """
        interval = float(os.environ.get(
            "SHOPAI_REFLECTION_DECAY_INTERVAL_SEC",
            self._REFLECTION_DECAY_INTERVAL_SEC,
        ))
        max_idle = float(os.environ.get(
            "SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC",
            self._REFLECTION_DECAY_MAX_IDLE_SEC,
        ))
        # Wave 7 (GAP-18): validate against operator typos. A
        # max_idle < 60s would retire every rule on every pass;
        # clamp to a 60s floor and warn loudly.
        if max_idle < 60.0:
            logger.warning(
                "SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC=%.1f is below "
                "60s floor — clamping to 60s to prevent mass retirement",
                max_idle,
            )
            max_idle = 60.0
        synth = getattr(self, "_reflection_synth", None)
        if synth is None:
            return []
        last = getattr(self, "_last_reflection_decay_at", 0.0)
        # last == 0.0 means "never decayed before" — run once on
        # the first tick so operators see the counter move at
        # startup, then respect the throttle interval thereafter.
        if last > 0.0 and (now - last) < interval:
            return []
        self._last_reflection_decay_at = now
        logger.debug(
            "reflection decay running: max_idle=%.0fs, interval=%.0fs",
            max_idle, interval,
        )
        try:
            return list(
                synth.decay_stale_rules(
                    max_idle, now=now,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("reflection decay failed: %s", exc)
            return []

    def _inject_sla_breaches(
        self,
        phase_errors: dict[str, str],
    ) -> None:
        """Poll the SLA tracker and inject breached subsystems into
        *phase_errors* so the reflection synthesizer can mine
        recurring adapter degradation.

        Wave 7 #2 (GAP-1): before this fix, SLA breaches were
        surfaced on ``/api/status`` but never entered the error
        mining pipeline, so a chronically-failing adapter could
        never promote a SOFT block rule.

        Fail-soft — any import or reporting failure is swallowed
        so this helper never breaks the cycle.
        """
        try:
            from core.telemetry.metrics_collector import (
                MetricsCollector as _TM,
            )
            tracker = _TM().get_sla_tracker()
            report = tracker.get_report()  # all-subsystems report
            subsystems = report.get("subsystems") or {}
            for subsys, data in subsystems.items():
                if not isinstance(data, dict):
                    continue
                if data.get("status") != "breached":
                    continue
                breaches = data.get("breaches") or []
                phase_errors[f"sla_breach::{subsys}"] = (
                    f"SLA breached on {subsys}: {', '.join(breaches)}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SLA breach injection failed: %s", exc)

    def _run_cognitive_phase(
        self, legacy_cycle_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run one Mind cycle and return its report dict.

        Called from run_cycle() when cognitive_mode is "shadow" or
        "primary". The cognitive cycle is independent — failures
        here are caught and logged but don't propagate.
        """
        if self._cognitive_mind is None:
            return None
        try:
            # Pass legacy data so the Mind's perceive phase has
            # something to read
            report = self._cognitive_mind.run_cycle(inputs={
                "legacy_cycle_id": legacy_cycle_result.get("cycle_id"),
                "store_id": legacy_cycle_result.get("store_id"),
                "phases_summary": list(
                    (legacy_cycle_result.get("phases") or {}).keys()
                ),
            })
            return report.to_dict()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cognitive Mind cycle failed: %s", exc)
            return {"error": str(exc)}

    def run_cognitive_cycle(self) -> dict[str, Any]:
        """Run a standalone cognitive cycle (no legacy phases).

        Used by `shopai mind cycle` and by daemons that want the
        cognitive loop without the legacy 39-phase machinery.
        Returns the CycleReport as a dict, or an error dict if no
        Mind is wired.
        """
        if self._cognitive_mind is None:
            return {
                "error": "no cognitive Mind wired into the controller",
            }
        try:
            report = self._cognitive_mind.run_cycle()
            return report.to_dict()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Standalone cognitive cycle failed")
            return {"error": str(exc)}

    def attach_cognitive_mind(
        self,
        mind: Any,
        *,
        mode: str = "shadow",
    ) -> None:
        """Attach a cognitive Mind to an already-built controller.

        Args:
            mind: a core.cognitive.mind.Mind instance
            mode: "off" | "shadow" | "primary" (see __init__)
        """
        self._cognitive_mind = mind
        if mode in ("off", "shadow", "primary"):
            self._cognitive_mode = mode

    @property
    def cognitive_mode(self) -> str:
        return self._cognitive_mode

    # ── Phase Implementations ────────────────────────────────

    def _phase_data(self, store_id: str) -> dict[str, Any]:
        """Phase 1: Fetch current store data (sync first, then read from DB)."""
        if not self._data_provider or not self._store_manager:
            return {}

        # Sync from Shopify first if possible
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(self._store_manager)
            sync.sync_store(store_id)
        except Exception as exc:
            logger.debug("Pre-cycle sync: %s", exc)

        # Now read from DB (freshly synced). Pre-cleanup the empty
        # case fell back to ``data_provider._mock_*`` (5 fake
        # products, 5 fake orders, 4 fake customers) and labelled
        # the source as ``"mock"`` — every cycle that ran against
        # an unconfigured store quietly trained on fiction. The
        # mock helpers are gone; missing data now stays empty and
        # the source is labelled ``"empty"`` so downstream phases
        # can either skip or short-circuit.
        data: dict[str, Any] = {"store_id": store_id, "source": "database"}
        products = self._store_manager.get_products(store_id)
        orders = self._store_manager.get_orders(store_id)
        customers = self._store_manager.get_customers(store_id)

        data["products"] = products or []
        data["order_data"] = orders or []
        data["customer_data"] = customers or []

        if not products and not orders and not customers:
            data["source"] = "empty"

        return data

    _LEGACY_ANALYSIS_ENGINES = (
        "pricing", "inventory", "product_ranking",
        "customer_segmentation", "product_research",
    )

    def _select_analysis_engines(self) -> list[str]:
        """Pick the analysis-phase engine list for this cycle.

        Default: legacy 5-engine hardcoded list. When
        ``use_engine_recommender=True``: consult the brain stack's
        engine recommender so the goal-feedback / EMA loop actually
        drives what runs. Recommender failure or empty pick list
        falls back to the legacy list — the autonomous loop must
        not silently run zero engines if the brain stack hiccups.
        """
        legacy = list(self._LEGACY_ANALYSIS_ENGINES)
        if not self._use_engine_recommender:
            return legacy
        try:
            from core.brain.engine_recommender import recommend_engines
            result = recommend_engines(
                limit=5, include_alternatives=False,
            )
        except Exception as exc:
            logger.warning(
                "engine recommender raised, falling back to legacy "
                "analysis list: %s", exc,
            )
            return legacy
        if not result.primary:
            logger.debug(
                "engine recommender returned empty picks; "
                "using legacy analysis list",
            )
            return legacy
        picks = [r.engine for r in result.primary]
        logger.info(
            "analysis engines (recommender-driven, goal=%s): %s",
            result.active_goal, picks,
        )
        return picks

    def _phase_analyze(self, store_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Run key analysis engines + AI reasoning."""
        from engines.registry import get_engine

        engines_to_run = self._select_analysis_engines()
        results: dict[str, Any] = {}

        for engine_name in engines_to_run:
            try:
                engine = get_engine(engine_name)
                if not engine:
                    continue
                # Build engine-compatible input
                engine_data = self._build_engine_input(engine_name, data)
                result = engine.run(engine_data)
                results[engine_name] = result if isinstance(result, dict) else {"status": "error", "error": "engine returned non-dict"}
            except Exception as exc:
                logger.warning("Engine %s failed: %s", engine_name, exc)
                results[engine_name] = {"status": "error", "error": str(exc)}

        # AI-enhanced analysis layer
        try:
            from core.ai.reasoning import ai_reason
            ai_pricing = ai_reason("pricing_optimization", products=data.get("products", []))
            if ai_pricing.get("recommendations"):
                results["ai_pricing"] = {
                    "status": "success",
                    "data": ai_pricing,
                    "source": ai_pricing.get("source", "unknown"),
                }
            ai_inventory = ai_reason("inventory_management", products=data.get("products", []))
            if ai_inventory.get("recommendations"):
                results["ai_inventory"] = {
                    "status": "success",
                    "data": ai_inventory,
                    "source": ai_inventory.get("source", "unknown"),
                }
        except Exception as exc:
            logger.debug("AI reasoning layer: %s", exc)

        return results

    def _phase_decide(self, store_id: str, analysis: dict[str, Any],
                      brain_decisions: list[dict] | None = None) -> list[dict[str, Any]]:
        """Phase 3: Convert brain decisions + analysis to proposed actions."""
        if not self._action_executor:
            return []

        all_decisions: list[dict[str, Any]] = []

        # Brain decisions → actions
        for dec in (brain_decisions or []):
            action = self._action_executor.propose_action({
                "type": dec.get("type", "brain_recommendation"),
                "store_id": store_id,
                "engine": "brain",
                "confidence": dec.get("confidence", 0.7),
                "reason": dec.get("reason", ""),
                "params": {"priority": dec.get("priority", 4)},
            })
            all_decisions.append(action)

        # From engine results — convert to actions
        # Inventory alerts
        inv = analysis.get("inventory", {})
        if isinstance(inv, dict) and inv.get("status") != "error":
            inv_data = inv.get("data", {})
            if isinstance(inv_data, dict):
                for alert in inv_data.get("alerts", [])[:5]:
                    if isinstance(alert, dict) and alert.get("severity") in ("critical", "high"):
                        all_decisions.append(self._action_executor.propose_action({
                            "type": "inventory_alert",
                            "store_id": store_id,
                            "engine": "inventory",
                            "confidence": 0.85,
                            "reason": alert.get("message", str(alert)[:80]),
                            "params": alert,
                        }))

        # Pricing recommendation — only if it RAISES price or has competitor data
        pr = analysis.get("pricing", {})
        if isinstance(pr, dict) and pr.get("status") != "error":
            pr_data = pr.get("data", {})
            if isinstance(pr_data, dict) and pr_data.get("recommended_price"):
                rec_price = pr_data["recommended_price"]
                # Get current price from first product in data
                products = data.get("products", []) if hasattr(self, '_last_data') else []
                current_price = products[0].get("price", 0) if products else 0

                # Only propose if raising price or confidence is high
                if rec_price > current_price or pr_data.get("confidence", 0) > 0.7:
                    all_decisions.append(self._action_executor.propose_action({
                        "type": "pricing_recommendation",
                        "store_id": store_id,
                        "engine": "pricing",
                        "confidence": pr_data.get("confidence", 0.5),
                        "reason": pr_data.get("rationale", "")[:100],
                        "params": {
                            "recommended_price": rec_price,
                            "strategy": pr_data.get("strategy", ""),
                        },
                    }))

        # From AI reasoning recommendations
        for key in ("ai_pricing", "ai_inventory"):
            result = analysis.get(key, {})
            if not isinstance(result, dict) or result.get("status") == "error":
                continue
            data = result.get("data", {})
            for rec in data.get("recommendations", []):
                if not isinstance(rec, dict):
                    continue
                # Convert AI recommendation to action
                if rec.get("recommended_price") and rec.get("product_id"):
                    action = self._action_executor.propose_action({
                        "type": "update_price",
                        "store_id": store_id,
                        "engine": key,
                        "confidence": rec.get("confidence", 0.5),
                        "reason": rec.get("reason", "AI recommendation"),
                        "params": {
                            "product_id": rec.get("product_id", ""),
                            "variant_id": rec.get("variant_id", ""),
                            "price": rec["recommended_price"],
                        },
                    })
                    all_decisions.append(action)
                elif rec.get("action") == "urgent_restock" or rec.get("priority") == "critical":
                    action = self._action_executor.propose_action({
                        "type": "alert",
                        "store_id": store_id,
                        "engine": key,
                        "confidence": rec.get("confidence", 0.8),
                        "reason": rec.get("reason", "Urgent attention needed"),
                        "params": {"product": rec.get("product", ""), "action": rec.get("action", "")},
                    })
                    all_decisions.append(action)

        return all_decisions

    def _capture_all_domains(self, store_id: str, data: dict,
                             analysis: dict, cycle_result: dict,
                             brain_decisions: list,
                             smart_exec: dict) -> dict[str, int]:
        """Capture data into all 12 domains for comprehensive intelligence."""
        from core.data.architecture import get_data_architecture
        da = get_data_architecture()
        captured: dict[str, int] = {}

        products = data.get("products", [])
        orders = data.get("order_data", data.get("orders", []))

        # 1. FEEDBACK domain — data quality issues as feedback
        dq = cycle_result.get("phases", {}).get("data_quality", {})
        if dq.get("issues", 0) > 0:
            da.capture("feedback", {
                "source": "data_quality",
                "topic": dq.get("top_issue", "")[:80],
                "sentiment": "negative" if dq.get("score", 100) < 80 else "neutral",
                "urgency": "high" if dq.get("score", 100) < 50 else "low",
                "score": dq.get("score", 0),
            }, source="system", store_id=store_id)
            captured["feedback"] = 1

        # 2. EXPERIMENT domain — each smart execution is an experiment
        se_results = smart_exec.get("results", []) if isinstance(smart_exec, dict) else []
        for se in se_results:
            da.capture("experiment", {
                "hypothesis": f"{se.get('action_type', 'unknown')} will improve store",
                "experiment_type": se.get("mode", "simulate"),
                "variants": 1,
                "sample_size": len(products),
                "confidence_level": se.get("confidence", 0),
                "result_score": se.get("score", 0),
            }, source="smart_executor", store_id=store_id,
                score=se.get("score", 3.0))
        captured["experiment"] = len(se_results)

        # 3. FEATURE domain — extracted features from this cycle
        brain = cycle_result.get("phases", {}).get("brain", {})
        if brain:
            da.capture("feature", {
                "feature_name": "health_score",
                "value": brain.get("health_score", 0),
                "data_type": "numeric",
                "source_domain": "brain",
                "freshness": 1.0,
            }, source="brain", store_id=store_id, score=4.0)
            da.capture("feature", {
                "feature_name": "opportunity_count",
                "value": brain.get("opportunities", 0),
                "data_type": "numeric",
                "source_domain": "brain",
                "freshness": 1.0,
            }, source="brain", store_id=store_id, score=3.5)
        captured["feature"] = 2

        # 4. KNOWLEDGE domain — learned rules and strategies
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
            rules = mi.get_rules()
            for r in rules[:5]:
                rc = r.get("content", {})
                if isinstance(rc, dict):
                    da.capture("knowledge", {
                        "content": rc.get("rule", str(rc)[:100]),
                        "knowledge_type": "rule",
                        "domain": r.get("category", ""),
                        "confidence": r.get("confidence", 0.5),
                        "evidence_count": r.get("evidence_count", 0),
                    }, source="memory_intelligence", store_id=store_id,
                        score=r.get("score", 3.0))
            captured["knowledge"] = len(rules[:5])
        except Exception as exc:
            logger.warning("learn_capture knowledge failed: %s", exc)
            captured["knowledge"] = 0

        # 5. SYSTEM domain — cycle performance metrics
        da.capture("system", {
            "event_type": "cycle_complete",
            "component": "autonomous_controller",
            "severity": "info",
            "latency_ms": int(cycle_result.get("duration_s", 0) * 1000),
            "layers_run": cycle_result.get("phases", {}).get("layers", {}).get("layers_run", 0),
            "insights": cycle_result.get("phases", {}).get("layers", {}).get("total_insights", 0),
        }, source="controller", store_id=store_id, score=4.0)
        captured["system"] = 1

        # 6. SIMULATION domain — smart execution simulations
        for se in se_results:
            predicted = se.get("predicted_outcome", {})
            if predicted:
                da.capture("simulation", {
                    "scenario": se.get("action_type", "unknown"),
                    "scenario_type": "action_simulation",
                    "predicted": predicted.get("estimated_revenue_change_pct", 0),
                    "confidence": se.get("confidence", 0),
                    "variables": len(predicted),
                    "practical_value": se.get("score", 0) / 5.0,
                }, source="smart_executor", store_id=store_id,
                    score=se.get("score", 3.0))
        captured["simulation"] = len(se_results)

        # 7. MARKETING domain — skill recommendations as marketing insights
        skills = cycle_result.get("phases", {}).get("skills", {})
        if skills.get("recommended", 0) > 0:
            for skill_name in skills.get("top", [])[:3]:
                da.capture("marketing", {
                    "channel": "ai_recommendation",
                    "campaign_type": skill_name,
                    "audience_size": len(data.get("customer_data", data.get("customers", []))),
                    "spend": 0,
                    "impressions": 0,
                    "clicks": 0,
                    "conversions": 0,
                }, source="skills", store_id=store_id, score=3.5)
        captured["marketing"] = min(skills.get("recommended", 0), 3)

        # Capture brain decisions as marketing opportunities
        for dec in brain_decisions[:2]:
            da.capture("marketing", {
                "channel": "brain_decision",
                "campaign_type": dec.get("type", "recommendation"),
                "audience_size": 0,
                "spend": 0,
            }, source="brain", store_id=store_id, score=3.5)
        captured["marketing"] += min(len(brain_decisions), 2)

        # 8. Feed competitor prices to price history
        try:
            from data_pipeline.tracking.price_history import get_price_history
            ph = get_price_history()
            comp_data = data.get("competitor_data", [])
            comp_count = 0
            for comp in comp_data:
                if isinstance(comp, dict):
                    pid = comp.get("product_id", "")
                    for cp in comp.get("competitor_prices", []):
                        if isinstance(cp, dict) and cp.get("price"):
                            ph.record_competitor_price(
                                pid, cp.get("competitor", "unknown"),
                                float(cp["price"]),
                            )
                            comp_count += 1
            captured["competitor_prices"] = comp_count
        except Exception as exc:
            logger.warning("learn_capture competitor_prices failed: %s", exc)

        # 9. Auto-complete mature A/B experiments
        try:
            from core.system.ab_testing import get_ab_testing
            ab = get_ab_testing()
            active = ab.get_active()
            completed_count = 0
            for exp in active:
                exp_id = exp.get("id", "")
                if not exp_id:
                    continue
                # Complete if has enough observations
                analysis = ab.analyze(exp_id)
                variants = analysis.get("variants", {})
                min_samples = min(
                    (v.get("sample_size", 0) for v in variants.values()),
                    default=0,
                )
                if min_samples >= 3:  # Enough data to conclude
                    ab.complete(exp_id)
                    completed_count += 1
            captured["experiments_completed"] = completed_count
        except Exception as exc:
            logger.warning("learn_capture experiments_completed failed: %s", exc)

        return captured

    def _phase_execute(self) -> list[dict[str, Any]]:
        """Phase 4: Execute approved actions."""
        if not self._action_executor:
            return []

        if self._auto_approve:
            # In auto mode, actions were already executed when proposed
            return self._action_executor.get_action_log(limit=20)

        # In manual mode, only execute pre-approved actions
        return []

    def _phase_learn(self, store_id: str, cycle_id: str,
                     analysis: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
        """Phase 5: Track outcomes and update learning weights."""
        if not self._learning_pipeline:
            return {"status": "skipped"}

        return self._learning_pipeline.process_cycle(
            store_id=store_id,
            cycle_id=cycle_id,
            analysis_results=analysis,
            execution_results=executions,
        )

    @staticmethod
    def _build_engine_input(engine_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build engine-compatible input from raw store data.

        Most engines expect: {status: "success", data: {product: {...}, ...}}
        Some (product_research) expect: {products: [...]}
        """
        products = data.get("products", [])
        orders = data.get("order_data", [])
        customers = data.get("customer_data", [])

        # Engines that take the flat format directly
        if engine_name in ("product_research",):
            return {"products": products}

        # Standard engine format: {status, data: {...}}
        product = {}
        for p in products:
            if p.get("cost", 0) > 0:
                product = p
                break
        if not product and products:
            product = products[0]

        # Customer segmentation needs customers at top level of data
        if engine_name == "customer_segmentation":
            return {
                "status": "success",
                "data": {"customer_data": customers, "customers": customers},
                "meta": {"engine": engine_name},
                "error": None,
            }

        # Map DB field names to engine field names
        if product:
            product = dict(product)
            product.setdefault("cogs", product.get("cost", 0))
            product.setdefault("shipping_cost", 0)
            product.setdefault("weight_kg", product.get("weight", 0))

        engine_data: dict[str, Any] = {
            "status": "success",
            "data": {
                "product": product,
                "products": products,
                "order_data": orders,
                "customer_data": customers,
                "inventory_data": [
                    {"product_id": p.get("id"), "name": p.get("name"),
                     "quantity": p.get("inventory_quantity", 0),
                     "price": p.get("price", 0), "cost": p.get("cost", 0)}
                    for p in products
                ],
            },
            "meta": {"engine": engine_name},
            "error": None,
        }
        return engine_data

    # ── Auto-Run ─────────────────────────────────────────────

    def start(self, interval_seconds: int = 600) -> dict[str, Any]:
        """Start autonomous operation."""
        if self._running:
            return {"status": "already_running"}

        self.initialize()
        self._cycle_interval = interval_seconds
        self._running = True
        self._cycle_thread = threading.Thread(
            target=self._auto_cycle_loop, daemon=True, name="shopai-autonomous"
        )
        self._cycle_thread.start()
        logger.info("Autonomous mode started (every %ds)", interval_seconds)
        return {"status": "started", "interval": interval_seconds}

    def stop(self) -> dict[str, Any]:
        """Stop autonomous operation."""
        self._running = False
        logger.info("Autonomous mode stopped after %d cycles", self._cycle_count)
        return {"status": "stopped", "cycles_completed": self._cycle_count}

    def _auto_cycle_loop(self) -> None:
        while self._running:
            try:
                stores = self._store_manager.list_stores() if self._store_manager else []
                for store in stores:
                    if not self._running:
                        break
                    self.run_cycle(store["store_id"])
            except Exception as exc:
                logger.error("Auto-cycle error: %s", exc)

            for _ in range(self._cycle_interval):
                if not self._running:
                    break
                time.sleep(1)

    # ── Status & History ─────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles_completed": self._cycle_count,
            "auto_approve": self._auto_approve,
            "interval_s": self._cycle_interval,
            "pending_actions": len(self._action_executor.get_pending()) if self._action_executor else 0,
            "performance": self._performance_tracker.get_summary() if self._performance_tracker else {},
        }

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._cycle_history[-limit:]


class LearningPipeline:
    """Connects action outcomes to the learning system.

    After each cycle:
      1. Record what decisions were made
      2. Compare with previous outcomes
      3. Update Bayesian weights
      4. Store learning in episodic memory
    """

    def __init__(self, store_manager: Any = None) -> None:
        self._store_manager = store_manager
        self._outcome_tracker = None
        self._learning_engine = None

    def _init_components(self) -> None:
        if not self._outcome_tracker:
            try:
                from core.learning.outcome_tracker import OutcomeTracker
                self._outcome_tracker = OutcomeTracker()
            except Exception as exc:
                logger.warning("OutcomeTracker init failed: %s", exc)
        if not self._learning_engine:
            try:
                from core.learning.learning_engine import LearningEngine
                self._learning_engine = LearningEngine()
            except Exception as exc:
                logger.warning("LearningEngine init failed: %s", exc)

    def process_cycle(self, store_id: str, cycle_id: str,
                      analysis_results: dict[str, Any],
                      execution_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Process a complete cycle through the learning pipeline."""
        self._init_components()

        learning_result: dict[str, Any] = {
            "decisions_recorded": 0,
            "outcomes_recorded": 0,
            "patterns_found": 0,
            "weight_updates": 0,
        }

        # Step 1: Record decisions from analysis
        for engine_name, result in analysis_results.items():
            if result.get("status") == "error":
                continue
            try:
                if self._outcome_tracker:
                    decision_id = f"{cycle_id}_{engine_name}"
                    self._outcome_tracker.record_decision(
                        decision_id, engine_name,
                        {"engine": engine_name, "result_summary": _summarize(result)},
                    )
                    learning_result["decisions_recorded"] += 1
            except Exception as exc:
                logger.debug("Decision recording failed: %s", exc)

        # Step 2: Record outcomes from executions
        for execution in execution_results:
            if not isinstance(execution, dict):
                continue
            try:
                if self._outcome_tracker and execution.get("engine"):
                    decision_id = f"{cycle_id}_{execution['engine']}"
                    self._outcome_tracker.record_outcome(
                        decision_id, execution["engine"],
                        {
                            "success": execution.get("status") == "executed",
                            "action_type": execution.get("type", ""),
                            "duration_s": execution.get("duration_s", 0),
                        },
                    )
                    learning_result["outcomes_recorded"] += 1
            except Exception as exc:
                logger.debug("Outcome recording failed: %s", exc)

        # Step 3: Extract patterns and update weights
        try:
            patterns = self._extract_patterns(analysis_results)
            learning_result["patterns_found"] = len(patterns)
            weight_updates = self._update_weights(patterns)
            learning_result["weight_updates"] = weight_updates
        except Exception as exc:
            logger.debug("Pattern extraction failed: %s", exc)

        # Step 4: Store in episodic memory
        try:
            self._store_episode(store_id, cycle_id, learning_result)
        except Exception as exc:
            logger.warning("Episode storage failed: %s", exc)

        learning_result["status"] = "complete"
        return learning_result

    def _extract_patterns(self, analysis_results: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract actionable patterns from analysis results."""
        patterns = []
        _insight_keys = (
            "recommendations", "alerts", "reorder_plan", "ranked_products",
            "winners", "segments", "opportunities", "trends",
            "stockout_risks", "churn_predictions",
        )

        for engine_name, result in analysis_results.items():
            if not isinstance(result, dict) or result.get("status") == "error":
                continue

            data = result.get("data", {})
            if not isinstance(data, dict):
                continue

            # Extract patterns from any list output
            for key in _insight_keys:
                items = data.get(key, [])
                if not isinstance(items, list) or not items:
                    continue
                for item in items[:5]:
                    if isinstance(item, dict):
                        patterns.append({
                            "engine": engine_name,
                            "type": item.get("type", item.get("action", key)),
                            "confidence": float(item.get("confidence",
                                            item.get("score", 0.5)) or 0.5),
                            "impact": item.get("expected_impact",
                                     item.get("impact", item.get("severity", "medium"))),
                        })

        return patterns

    def _update_weights(self, patterns: list[dict[str, Any]]) -> int:
        """Update Bayesian learning weights based on patterns."""
        try:
            from core.intelligence.loop.stage_learn import _update_weight
        except ImportError:
            # Fallback: use MemoryIntelligence rule success as weight signal
            return self._update_weights_from_rules()

        updates = 0
        for pattern in patterns:
            engine = pattern.get("engine", "")
            # Any pattern with confidence > 0.3 counts (was 0.7 — too strict)
            confidence = pattern.get("confidence", 0)
            if confidence > 0.3 or engine:
                if "pricing" in engine or "price" in engine:
                    _update_weight("price", 1)
                    updates += 1
                elif "inventory" in engine or "demand" in engine:
                    _update_weight("demand", 1)
                    updates += 1
                elif "margin" in engine:
                    _update_weight("margin", 1)
                    updates += 1
                elif "competition" in engine or "competitor" in engine:
                    _update_weight("competition", 1)
                    updates += 1

        return updates

    @staticmethod
    def _update_weights_from_rules() -> int:
        """Fallback weight update using MemoryIntelligence rules."""
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
            rules = mi.get_rules()
            updates = 0
            for r in rules:
                if r.get("success_count", 0) > 0:
                    updates += 1
            return updates
        except Exception:
            return 0

    def _store_episode(self, store_id: str, cycle_id: str, learning: dict[str, Any]) -> None:
        """Store learning episode in long-term memory."""
        try:
            from memory.long_term.persistent_store import PersistentStore
            store = PersistentStore()
            store.store(
                f"learning_{cycle_id}",
                learning,
                namespace="learning_history",
                metadata={"store_id": store_id, "cycle_id": cycle_id},
            )
        except Exception as exc:
            logger.warning("PersistentStore episode write failed: %s", exc)

    def get_learning_summary(self) -> dict[str, Any]:
        """Get summary of what the system has learned."""
        self._init_components()
        result: dict[str, Any] = {"engines": {}}

        if self._learning_engine:
            try:
                system_analysis = self._learning_engine.analyze_system()
                result["system"] = system_analysis
            except Exception as exc:
                logger.warning("Learning system analysis failed: %s", exc)

        # Get current weights
        try:
            from core.intelligence.loop.weight_manager import _learned_weights
            result["weights"] = dict(_learned_weights)
        except Exception:
            result["weights"] = {}

        return result


class PerformanceTracker:
    """Tracks autonomous controller performance over time."""

    def __init__(self, store_manager: Any = None) -> None:
        self._cycles: list[dict[str, Any]] = []
        self._store_manager = store_manager

    def record_cycle(self, cycle_result: dict[str, Any]) -> None:
        self._cycles.append({
            "cycle_id": cycle_result.get("cycle_id", ""),
            "store_id": cycle_result.get("store_id", ""),
            "duration_s": cycle_result.get("duration_s", 0),
            "insights": cycle_result.get("phases", {}).get("analysis", {}).get("insights", 0),
            "actions_proposed": cycle_result.get("phases", {}).get("decisions", {}).get("proposed", 0),
            "actions_executed": cycle_result.get("phases", {}).get("execution", {}).get("executed", 0),
            "learning": cycle_result.get("phases", {}).get("learning", {}),
            "timestamp": time.time(),
        })
        if len(self._cycles) > 500:
            self._cycles = self._cycles[-500:]

    def get_summary(self) -> dict[str, Any]:
        if not self._cycles:
            return {"total_cycles": 0}

        total = len(self._cycles)
        total_insights = sum(c.get("insights", 0) for c in self._cycles)
        total_actions = sum(c.get("actions_proposed", 0) for c in self._cycles)
        total_executed = sum(c.get("actions_executed", 0) for c in self._cycles)
        avg_duration = sum(c.get("duration_s", 0) for c in self._cycles) / total

        return {
            "total_cycles": total,
            "total_insights": total_insights,
            "total_actions_proposed": total_actions,
            "total_actions_executed": total_executed,
            "avg_cycle_duration_s": round(avg_duration, 2),
            "learning_updates": sum(
                c.get("learning", {}).get("weight_updates", 0) for c in self._cycles
            ),
        }

    def get_trend(self, last_n: int = 10) -> dict[str, Any]:
        """Get recent performance trend."""
        recent = self._cycles[-last_n:]
        if len(recent) < 2:
            return {"trend": "insufficient_data"}

        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]

        first_insights = sum(c.get("insights", 0) for c in first_half) / len(first_half)
        second_insights = sum(c.get("insights", 0) for c in second_half) / len(second_half)

        if second_insights > first_insights * 1.1:
            trend = "improving"
        elif second_insights < first_insights * 0.9:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "recent_avg_insights": round(second_insights, 1),
            "previous_avg_insights": round(first_insights, 1),
        }


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of engine output for storage."""
    data = result.get("data", {})
    return {
        "status": result.get("status", "unknown"),
        "recommendations_count": len(data.get("recommendations", [])),
        "has_alerts": bool(data.get("alerts", [])),
    }
