"""Dashboard API — HTTP endpoints for monitoring and control.

Endpoints:
  GET  /api/status             — system status (+ adapter SLA summary)
  GET  /api/dashboard          — full dashboard data
  GET  /api/cycle              — run a cycle and return results
  GET  /api/alerts             — recent alerts
  GET  /api/report             — human-readable report
  GET  /api/memory             — memory intelligence stats
  GET  /api/metrics/adapters   — per-adapter SLA rollup (Wave 4 #3)
  GET  /api/cognitive          — Mind cognitive dispatcher stats (Wave 5 #B)
  GET  /api/memory/satellites  — SatelliteRouter layer stats (Wave 5 #B)
  GET  /api/policy/audit       — recent policy audit entries (Wave 5 #B)
  GET  /api/beliefs            — Bayesian belief posterior snapshot (Wave 6 #5)
  GET  /api/reflection         — Learned reflection-rule snapshot (Wave 6 #7)
  POST /api/webhook            — Shopify webhook receiver
"""
from __future__ import annotations
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from utils.logger import get_logger
from api.validation import validate_shop_url, validate_string, validate_webhook_topic
logger = get_logger("api.dashboard")


class DashboardAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard API."""

    def do_GET(self):
        path = self.path.split("?")[0]

        # Record every API request in data architecture
        try:
            from core.data.architecture import get_data_architecture
            get_data_architecture().capture("system", {
                "event_type": "api_request",
                "component": "dashboard_api",
                "severity": "info",
                "endpoint": path,
            }, source="api", score=3.0)
        except Exception as exc:
            logger.debug("data-architecture capture failed: %s", exc)

        if path == "/api/status":
            self._json_response(self._get_status())
        elif path == "/api/stores":
            self._json_response(self._get_stores())
        elif path == "/api/dashboard":
            self._json_response(self._get_dashboard())
        elif path == "/api/cycle":
            self._json_response(self._run_cycle())
        elif path == "/api/alerts":
            self._json_response(self._get_alerts())
        elif path == "/api/report":
            self._text_response(self._get_report())
        elif path == "/api/memory":
            self._json_response(self._get_memory())
        elif path == "/api/metrics/adapters":
            self._json_response(self._get_adapter_metrics())
        elif path == "/api/cognitive":
            self._json_response(self._get_cognitive_report())
        elif path == "/api/memory/satellites":
            self._json_response(self._get_satellite_stats())
        elif path == "/api/policy/audit":
            limit_raw = self.path.split("?", 1)[1] if "?" in self.path else ""
            limit = self._parse_limit(limit_raw, default=20, maximum=500)
            self._json_response(self._get_policy_audit(limit=limit))
        elif path == "/api/beliefs":
            limit_raw = self.path.split("?", 1)[1] if "?" in self.path else ""
            limit = self._parse_limit(limit_raw, default=50, maximum=500)
            self._json_response(self._get_belief_snapshot(limit=limit))
        elif path == "/api/launches":
            self._json_response(self._get_launches())
        elif path == "/api/ask":
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            q = (params.get("q") or [""])[0]
            self._json_response(self._get_ask(q))
        elif path == "/api/chat/sessions":
            self._json_response(self._get_chat_sessions())
        elif path == "/api/reason":
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            q = (params.get("q") or [""])[0]
            self._json_response(self._get_reason(q))
        elif path == "/api/similar":
            # /api/similar?q=...&k=5&level=1&category=launch
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            q = (params.get("q") or [""])[0]
            k = int((params.get("k") or ["5"])[0])
            level = int((params.get("level") or ["0"])[0])
            cat = (params.get("category") or [None])[0]
            self._json_response(self._get_similar(q, k, level, cat))
        elif path == "/api/reflection":
            limit_raw = self.path.split("?", 1)[1] if "?" in self.path else ""
            limit = self._parse_limit(limit_raw, default=50, maximum=500)
            self._json_response(self._get_reflection_snapshot(limit=limit))
        else:
            self._json_response({"error": "not_found", "endpoints": [
                "/api/status", "/api/dashboard", "/api/cycle",
                "/api/alerts", "/api/report", "/api/memory",
                "/api/metrics/adapters", "/api/cognitive",
                "/api/memory/satellites", "/api/policy/audit",
                "/api/beliefs", "/api/reflection", "/api/launches",
            ]}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/chat/send":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self._json_response({"error": "bad json"}, 400)
                return
            from core.brain.chat_session import send
            self._json_response(send(
                payload.get("session_id"),
                payload.get("question", ""),
            ))
            return
        if path == "/api/webhook":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            topic = self.headers.get("X-Shopify-Topic", "unknown")
            hmac_header = self.headers.get("X-Shopify-Hmac-Sha256", "")
            try:
                payload = json.loads(body)
                from core.system.webhook_handler import get_webhook_handler
                wh = get_webhook_handler()
                result = wh.process(topic, payload, hmac_header)
                self._json_response(result)
            except Exception as exc:
                logger.warning("webhook processing failed: %s", exc)
                self._json_response({"error": str(exc)[:100]}, 500)
        elif path == "/api/stores":
            # POST /api/stores — register new store
            try:
                payload = json.loads(body) if body else {}
                shop_url, err = validate_shop_url(payload.get("url", ""))
                if err:
                    self._json_response({"error": err}, 400)
                    return
                token, err = validate_string(
                    payload.get("token", ""), "token", required=True, max_len=256)
                if err:
                    self._json_response({"error": err}, 400)
                    return
                name, _ = validate_string(
                    payload.get("name", ""), "name", required=False, max_len=128)
                niche, _ = validate_string(
                    payload.get("niche", ""), "niche", required=False, max_len=64)

                from core.system.store_registry import get_store_registry
                reg = get_store_registry()
                result = reg.register(
                    shop_url=shop_url, token=token, name=name, niche=niche,
                )
                self._json_response(result)
            except json.JSONDecodeError as exc:
                self._json_response({"error": f"Invalid JSON body: {exc}"}, 400)
            except Exception as exc:
                logger.warning("store registration failed: %s", exc)
                self._json_response({"error": str(exc)[:100]}, 500)
        else:
            self._json_response({"error": "not_found"}, 404)

    def _json_response(self, data: dict, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _text_response(self, text: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode())

    @staticmethod
    def _get_stores() -> dict:
        try:
            from core.system.store_registry import get_store_registry
            reg = get_store_registry()
            return {"stores": reg.list_stores(), "stats": reg.get_stats()}
        except Exception as exc:
            return {"error": str(exc)[:100]}

    @staticmethod
    def _get_status() -> dict:
        result = {"status": "running", "timestamp": time.time()}
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            result["memory"] = mi.get_stats()
        except Exception as exc:
            logger.debug("memory stats unavailable: %s", exc)
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            result["data"] = da.get_stats()
        except Exception as exc:
            logger.debug("data-architecture stats unavailable: %s", exc)
        # Wave 4 #3: surface an adapter SLA rollup so operators hitting
        # /api/status can see which adapters are breaching their SLO
        # without a separate call to /api/metrics/adapters.
        try:
            from core.adapters.metrics import get_metrics
            sla = get_metrics().get_sla_report()
            result["adapters_sla"] = DashboardAPIHandler._summarise_sla(sla)
        except Exception as exc:
            logger.debug("adapter SLA rollup unavailable: %s", exc)
        # Wave 6 #15: compact learning-pipeline health snapshot so
        # /api/status tells operators at a glance whether the
        # learning feedback loop is working (patterns firing, rules
        # retained, beliefs fresh) without a separate call to
        # /api/reflection or /api/beliefs.
        try:
            result["learning"] = (
                DashboardAPIHandler._summarise_learning()
            )
        except Exception as exc:
            logger.debug("learning summary unavailable: %s", exc)
        return result

    @staticmethod
    def _summarise_sla(sla: dict) -> dict:
        """Compact an SLA report into a lightweight status summary.

        Keeps the per-adapter detail out of /api/status (that's what
        /api/metrics/adapters is for) and surfaces only the count
        of breached / degraded / ok adapters plus the list of any
        that are currently breaching.
        """
        if not isinstance(sla, dict):
            return {"total": 0, "ok": 0, "degraded": 0, "breached": 0, "breaching": []}
        subs = sla.get("subsystems", {}) if "subsystems" in sla else sla
        if not isinstance(subs, dict):
            return {"total": 0, "ok": 0, "degraded": 0, "breached": 0, "breaching": []}
        ok = deg = brk = 0
        breaching: list[str] = []
        for name, row in subs.items():
            status = (row or {}).get("status", "ok") if isinstance(row, dict) else "ok"
            if status == "breached":
                brk += 1
                breaching.append(name)
            elif status == "degraded":
                deg += 1
            else:
                ok += 1
        return {
            "total":     ok + deg + brk,
            "ok":        ok,
            "degraded":  deg,
            "breached":  brk,
            "breaching": breaching,
        }

    @staticmethod
    def _summarise_learning() -> dict[str, Any]:
        """Compact learning-pipeline health for /api/status.

        Wave 6 #15. Lightweight: reads active-pattern count from the
        synthesizer, SOFT-rule count from the policy store, and
        belief count from the belief store. Any failure degrades the
        field to ``None`` rather than blocking the response.
        """
        summary: dict[str, Any] = {
            "active_patterns": None,
            "soft_rules":      None,
            "beliefs":         None,
            "half_life":       None,
            "status":          "unknown",
        }
        active = 0
        firing = 0
        try:
            from core.reflection.synthesizer import get_default_synthesizer
            snap = get_default_synthesizer().snapshot()
            active = len(snap)
            summary["active_patterns"] = active
        except Exception as exc:
            logger.debug("active patterns unavailable: %s", exc)
        try:
            from engines.meta_governance.policy_store import (
                PolicyTier,
                get_default_store,
            )
            store = get_default_store()
            soft = store.list_rules(tier=PolicyTier.SOFT)
            summary["soft_rules"] = len(soft)
            # Count firing from stats.
            try:
                for stat in store.get_all_rule_stats():
                    if (
                        stat.get("source") == "learned"
                        and stat.get("matches", 0) > 0
                    ):
                        firing += 1
            except Exception as exc:
                logger.debug("firing-count stat walk failed: %s", exc)
        except Exception as exc:
            logger.debug("policy store soft-rule count failed: %s", exc)
        try:
            from core.mentality import get_default_belief_store
            bs = get_default_belief_store()
            summary["beliefs"] = len(bs.keys())
            summary["half_life"] = getattr(bs, "half_life_seconds", None)
        except Exception as exc:
            logger.debug("belief store unavailable: %s", exc)
        # Derive a compact status string.
        if summary["active_patterns"] is not None:
            if active == 0:
                summary["status"] = "idle"
            elif firing > 0:
                summary["status"] = "healthy"
            else:
                summary["status"] = "learning"
        return summary

    @staticmethod
    def _parse_limit(query: str, *, default: int, maximum: int) -> int:
        """Extract ``limit=<n>`` from a raw querystring, clamped to
        [1, maximum]. Returns *default* on any parse failure so the
        endpoint never 500s on bad input.
        """
        if not query:
            return default
        try:
            for part in query.split("&"):
                if "=" not in part:
                    continue
                key, val = part.split("=", 1)
                if key == "limit":
                    n = int(val)
                    return max(1, min(maximum, n))
        except Exception as exc:
            logger.debug("query-string parse failed: %s", exc)
        return default

    @staticmethod
    def _get_cognitive_report() -> dict:
        """Return the Mind cognitive dispatcher observability snapshot.

        Wave 5 #B: exposes Wave 4 #4's in-memory counters (call counts,
        error counts, recent ring buffer, cycles_run) over HTTP so
        operators can watch MBTI function activity without attaching
        a debugger. Fails soft — a missing Mind singleton returns an
        error envelope, never a 500.
        """
        try:
            from core.cognitive.mind import get_mind
            mind = get_mind()
            report = mind.cognitive_report()
            report["timestamp"] = time.time()
            return report
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_satellite_stats() -> dict:
        """Return SatelliteRouter layer stats (vector / graph / signal).

        Wave 5 #B: the satellite layers (Wave 2 #4, integrated Wave 3
        #3, reads exposed Wave 4 #2) track per-layer totals; this
        endpoint surfaces them so operators can see the memory
        augmentation is alive without opening a REPL.
        """
        try:
            from core.memory.unified_memory import get_unified_memory
            mem = get_unified_memory()
            router = mem.get_satellites()
            return {
                "layers":    router.stats(),
                "timestamp": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_policy_audit(limit: int = 20) -> dict:
        """Return recent policy audit entries (newest first).

        Wave 5 #B: the policy store writes every HARD / MEDIUM /
        SOFT decision to JSONL (Wave 2 #1); without an HTTP surface
        operators had to tail the file by hand. This endpoint
        bridges the gap. Querystring ``?limit=N`` caps the response
        size (default 20, max 500).
        """
        try:
            from engines.meta_governance.policy_store import get_default_store
            store = get_default_store()
            entries = store.read_audit(limit=limit)
            return {
                "entries":   entries,
                "count":     len(entries),
                "timestamp": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_belief_snapshot(limit: int = 50) -> dict:
        """Return the Bayesian belief posterior snapshot.

        Wave 6 #5: exposes the process-wide belief store written by
        Wave 6 #2 (``_update_beliefs_from_execution``) and read by
        Wave 6 #3 (``_check_belief_posterior``). Operators can now
        see exactly what the gate has learned without attaching a
        debugger — which keys have enough evidence, which are
        trending toward failure, which still look healthy.

        Wave 6 #12: surfaces decay telemetry on top of the Wave 6
        #11 ``half_life_seconds`` option. Each row carries
        ``last_updated_at`` (wall-clock of the last observe) and a
        derived ``age_seconds`` so operators can see how fresh the
        posterior is — critical once decay is active and stale
        beliefs silently drift back toward the prior. The response
        envelope gains ``half_life_seconds`` at top level so the
        dashboard can display the active decay configuration.

        Keys are sorted by the lower bound of the 95% credible
        interval (ascending) so the most at-risk actions float to
        the top. Querystring ``?limit=N`` caps the response size
        (default 50, max 500). Fails soft: a missing or unhealthy
        belief store returns an error envelope.
        """
        try:
            from core.mentality import get_default_belief_store
            store = get_default_belief_store()
            snap = store.snapshot()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

        now = time.time()
        rows: list[dict[str, Any]] = []
        for key, row in snap.items():
            try:
                lo, hi = store.credible_interval_95(key)
            except Exception as exc:
                logger.debug("credible interval fallback for %s: %s", key, exc)
                lo, hi = 0.0, 1.0
            last_updated_at = row.get("last_updated_at")
            age_seconds: float | None = None
            if last_updated_at is not None:
                try:
                    age_seconds = max(0.0, now - float(last_updated_at))
                except (TypeError, ValueError):
                    age_seconds = None
            rows.append({
                "key":             key,
                "alpha":           row["alpha"],
                "beta":            row["beta"],
                "mean":            round(float(row["mean"]), 4),
                "n":               row["n"],
                "ci_low":          round(float(lo), 4),
                "ci_high":         round(float(hi), 4),
                "last_updated_at": last_updated_at,
                "age_seconds": (
                    round(age_seconds, 3)
                    if age_seconds is not None
                    else None
                ),
            })
        # Sort by ci_low ascending — worst-case first — with ties
        # broken by mean ascending and then by n descending so
        # well-evidenced bad keys rank above thinly-evidenced ones.
        rows.sort(key=lambda r: (r["ci_low"], r["mean"], -r["n"]))
        total = len(rows)
        rows = rows[:limit]

        # Wave 6 #12: surface the store's half-life so operators
        # can see whether decay is active without shelling into
        # the process. Missing attribute (older store objects
        # injected by tests) falls back to None.
        try:
            half_life_seconds = getattr(
                store, "half_life_seconds", None,
            )
        except Exception as exc:
            logger.debug("half_life_seconds attr read failed: %s", exc)
            half_life_seconds = None

        return {
            "beliefs":           rows,
            "count":             len(rows),
            "total":             total,
            "half_life_seconds": half_life_seconds,
            "timestamp":         now,
        }

    @staticmethod
    def _get_chat_sessions() -> dict:
        try:
            from core.brain.chat_session import ChatStore
            return {"sessions": ChatStore.list_ids(limit=20)}
        except Exception as exc:
            return {"sessions": [], "error": str(exc)[:200]}

    @staticmethod
    def _get_ask(query: str) -> dict:
        """One-shot conversational Q&A backed by memory + LLM."""
        if not query:
            return {"error": "query string ?q=... required"}
        try:
            from core.brain.oracle import ask
            return ask(query).as_dict()
        except Exception as exc:
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_reason(query: str) -> dict:
        """Four-phase research → hypothesize → test → evaluate chain.
        Returns the ranked plan + step telemetry. Blocking: ~3-8 s."""
        if not query:
            return {"error": "query string ?q=... required"}
        try:
            from core.brain.reasoner import reason
            return reason(query).as_dict()
        except Exception as exc:
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_similar(query: str, k: int, level_min: int, category: str | None) -> dict:
        """Semantic retrieval endpoint — cosine over Gemini embeddings."""
        try:
            from core.memory.semantic_index import retrieve_similar, stats
            hits = retrieve_similar(
                query=query, k=max(1, min(k, 20)),
                level_min=level_min, category=category,
            )
            return {
                "query": query,
                "k": k, "level_min": level_min, "category": category,
                "hits": hits,
                "index": stats(),
            }
        except Exception as exc:
            return {"query": query, "hits": [], "error": str(exc)[:200]}

    @staticmethod
    def _get_launches() -> dict:
        """Return per-launch KPIs + kill / scale / monitor verdicts.

        Backed by :func:`core.autonomous.launch_evaluator.evaluate` —
        a pure aggregation over MemoryIntelligence events, safe to
        call frequently (no external HTTP).
        """
        try:
            from core.autonomous.launch_evaluator import evaluate
            report = evaluate()
            return {
                "summary": {
                    "tracked": report.launches_tracked,
                    "evaluated": report.launches_evaluated,
                    "kill": len(report.kill_recommendations),
                    "scale": len(report.scale_recommendations),
                    "monitor": len(report.monitor_recommendations),
                },
                "report": report.as_dict(),
            }
        except Exception as exc:
            logger.debug("launch evaluator failed: %s", exc)
            return {"summary": {"tracked": 0}, "error": str(exc)[:200]}

    @staticmethod
    def _get_reflection_snapshot(limit: int = 50) -> dict:
        """Return the learned-reflection-rule snapshot.

        Wave 6 #7: exposes the process-wide ReflectionSynthesizer
        pattern cache written by Wave 6 #6. Operators can now
        inspect what error patterns the synthesizer has mined and
        promoted — the same data the autonomous controller feeds
        back into the policy store as SOFT rules — without
        scraping the JSONL ledger.

        Rows are already sorted by ``last_seen`` descending inside
        :meth:`ReflectionSynthesizer.snapshot`. Querystring
        ``?limit=N`` caps the response size (default 50, max 500).
        Fails soft: a missing or unhealthy synthesizer returns an
        error envelope.
        """
        try:
            from core.reflection.synthesizer import get_default_synthesizer
            synth = get_default_synthesizer()
            rows = synth.snapshot()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

        # Wave 6 #8: enrich each pattern with activation stats from
        # the default policy store so operators can tell a useful
        # learned rule from a dead one in the same view. Fails
        # soft — a missing stats table just leaves the counters at
        # zero.
        stats_by_rule: dict[str, dict[str, Any]] = {}
        try:
            from engines.meta_governance.policy_store import get_default_store
            store = get_default_store()
            for row in store.get_all_rule_stats():
                stats_by_rule[row["rule_id"]] = row
        except Exception as exc:  # noqa: BLE001
            logger.debug("reflection: policy stats unavailable (%s)", exc)

        for row in rows:
            stat = stats_by_rule.get(row.get("rule_id", ""))
            row["matches"] = int(stat["matches"]) if stat else 0
            row["blocks"] = int(stat["blocks"]) if stat else 0
            row["last_matched_at"] = stat["last_matched_at"] if stat else None

        total = len(rows)

        # Wave 6 #14: aggregate learning-effectiveness metrics so
        # operators get a single "is the learning pipeline healthy?"
        # view without eyeballing every row. Built from in-memory
        # data already loaded (active patterns + enriched stats),
        # plus a lightweight SOFT-rule count from the store.
        learning_stats: dict[str, Any] = {}
        try:
            active = total  # active patterns in the synthesizer
            total_matches = sum(r.get("matches", 0) for r in rows)
            total_blocks = sum(r.get("blocks", 0) for r in rows)
            firing = sum(1 for r in rows if r.get("matches", 0) > 0)
            # SOFT rule count from the policy store (may differ from
            # synthesizer count if rules were added manually or if
            # the store drifted — the delta is itself diagnostic).
            soft_in_store = 0
            try:
                from engines.meta_governance.policy_store import (
                    PolicyTier,
                    get_default_store,
                )
                soft_in_store = len(
                    get_default_store().list_rules(tier=PolicyTier.SOFT),
                )
            except Exception as exc:
                logger.debug("soft-rule count unavailable: %s", exc)
            # Count RETIREMENT events from the audit log to derive
            # total-ever-promoted (active + retired).
            retired_count = 0
            try:
                from engines.meta_governance.policy_store import (
                    get_default_store,
                )
                for entry in get_default_store().read_audit(limit=500):
                    if entry.get("event") == "RETIREMENT":
                        retired_count += 1
            except Exception as exc:
                logger.debug("retirement audit count failed: %s", exc)
            total_ever = active + retired_count
            learning_stats = {
                "active_patterns":   active,
                "firing_patterns":   firing,
                "retired_count":     retired_count,
                "total_promoted":    total_ever,
                "soft_in_store":     soft_in_store,
                "total_matches":     total_matches,
                "total_blocks":      total_blocks,
                "effectiveness": (
                    round(firing / active, 4) if active > 0 else None
                ),
                "retention_rate": (
                    round(active / total_ever, 4)
                    if total_ever > 0
                    else None
                ),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("reflection: learning_stats failed (%s)", exc)

        rows = rows[:limit]

        # Wave 6 #16: surface the synthesizer's tuning parameters
        # so operators can see the promotion bar.
        config: dict[str, Any] = {}
        try:
            config = synth.config()
        except Exception as exc:
            logger.debug("synthesizer config unavailable: %s", exc)

        # Wave 6 #18: surface near-miss (pending) patterns from the
        # most recent run so operators get early warning of emerging
        # error trends before they fully qualify for promotion.
        pending: list[dict[str, Any]] = []
        try:
            report = getattr(synth, "last_report", None)
            if report is not None:
                pending = [p.as_dict() for p in report.pending_patterns]
        except Exception as exc:
            logger.debug("pending patterns unavailable: %s", exc)

        return {
            "patterns":         rows,
            "count":            len(rows),
            "total":            total,
            "pending_patterns": pending,
            "pending_count":    len(pending),
            "learning_stats":   learning_stats,
            "config":           config,
            "last_run_at":      getattr(synth, "last_run_at", None),
            "persist_path":     str(getattr(synth, "persist_path", "") or ""),
            "timestamp":        time.time(),
        }

    @staticmethod
    def _get_adapter_metrics() -> dict:
        """Return the full per-adapter SLA report.

        Wave 4 #3: operator endpoint for the Wave 2 #6 SLATracker
        feed that was fully wired through the metrics layer in
        Wave 3 #4. Always returns a dict — any failure inside the
        telemetry module degrades to ``{"error": "..."}`` so the
        endpoint never crashes the dashboard server.
        """
        try:
            from core.adapters.metrics import get_metrics
            report = get_metrics().get_sla_report()
            return {
                "report":    report,
                "summary":   DashboardAPIHandler._summarise_sla(report),
                "timestamp": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_dashboard() -> dict:
        try:
            from core.system.dashboard import get_dashboard
            return get_dashboard().generate()
        except Exception as exc:
            return {"error": str(exc)[:100]}

    @staticmethod
    def _run_cycle() -> dict:
        try:
            from core.system.auto_scheduler import get_scheduler
            return get_scheduler().run_once()
        except Exception as exc:
            return {"error": str(exc)[:100]}

    @staticmethod
    def _get_alerts() -> dict:
        try:
            from core.system.alerts import get_alert_system
            alerts = get_alert_system()
            return {"alerts": alerts.get_recent(20), "stats": alerts.get_stats()}
        except Exception as exc:
            logger.debug("alert system unavailable: %s", exc)
            return {"alerts": []}

    @staticmethod
    def _get_report() -> str:
        try:
            from core.system.auto_scheduler import get_scheduler
            sc = get_scheduler()
            if sc._last_result:
                from core.system.cycle_reporter import get_cycle_reporter
                return get_cycle_reporter().report(sc._last_result)
            return "No cycle run yet. GET /api/cycle first."
        except Exception as exc:
            return "Error: {}".format(exc)

    @staticmethod
    def _get_memory() -> dict:
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            return {
                "stats": mi.get_stats(),
                "rules": [{"category": r.get("category",""), "action": r.get("action",""),
                           "uses": r.get("use_count",0), "success": r.get("success_count",0)}
                          for r in mi.get_rules()],
                "strategies": [{"category": s.get("category",""),
                               "content": s.get("content",{})}
                              for s in mi.get_strategies()],
                "meta": mi.get_meta_stats(),
            }
        except Exception as exc:
            return {"error": str(exc)[:100]}

    def log_message(self, format, *args):
        pass  # Suppress default logging


def start_api(host: str = "0.0.0.0", port: int = 8080) -> dict:
    """Start the dashboard API server in a background thread."""
    server = HTTPServer((host, port), DashboardAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="shopai-api")
    thread.start()
    logger.info("Dashboard API started on %s:%d", host, port)
    return {"status": "started", "host": host, "port": port}
