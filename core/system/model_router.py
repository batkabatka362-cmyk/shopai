"""Model Router — routes data tasks to local models with async queue.

Distributes work across 3 models:
  mistral  → ANALYZE (evaluate, score, classify, compare)
  qwen2.5  → WORK (extract, calculate, transform, parse)
  llama3.2 → CREATE (write, generate, describe, compose)

Every task:
  1. Classify → which model?
  2. Build prompt with data context (memory + rules)
  3. Queue for execution
  4. Record result in DataArchitecture
  5. Learn from outcome

Handles slow inference gracefully:
  - Async queue (non-blocking)
  - Timeout with heuristic fallback
  - Batch processing for efficiency
"""
from __future__ import annotations
import json
import os
import queue
import threading
import time
import urllib.request
from typing import Any
from utils.logger import get_logger
logger = get_logger("model.router")

OLLAMA_URL = os.environ.get("SHOPAI_OLLAMA_URL", "http://127.0.0.1:11434")

MODEL_ROLES = {
    "analyze": "mistral",
    "work": "qwen2.5",
    "create": "llama3.2",
}

TASK_ROLE_MAP = {
    "analyze_product": "analyze",
    "score_product": "analyze",
    "compare_prices": "analyze",
    "classify_category": "analyze",
    "extract_keywords": "work",
    "calculate_margin": "work",
    "parse_description": "work",
    "generate_tags": "work",
    "write_description": "create",
    "write_social_post": "create",
    "write_email": "create",
    "write_blog": "create",
}


class ModelRouter:
    """Routes data tasks to the right local model."""

    def __init__(self):
        self._queue = queue.Queue(maxsize=100)
        self._results = {}
        self._worker = None
        self._running = False
        self._stats = {"total": 0, "success": 0, "fallback": 0, "timeout": 0}
        self._timeout = 10  # seconds per task (fast fallback if slow)

    def start_worker(self):
        """Start background worker thread."""
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._process_queue,
                                        daemon=True, name="model-router")
        self._worker.start()
        logger.info("Model router started")

    def stop(self):
        self._running = False

    def is_available(self):
        """Check if Ollama is reachable."""
        try:
            req = urllib.request.Request("{}/api/tags".format(OLLAMA_URL))
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            return False

    # ── SUBMIT TASK ──────────────────────────────

    def submit(self, task_type, data, store_id=""):
        """Submit a task. Returns task_id. Non-blocking."""
        task_id = "task_{:.0f}".format(time.time() * 1000)
        role = TASK_ROLE_MAP.get(task_type, "work")
        model = MODEL_ROLES.get(role, "mistral")

        # Build prompt with data context
        prompt = self._build_prompt(task_type, data)

        task = {
            "id": task_id,
            "type": task_type,
            "role": role,
            "model": model,
            "prompt": prompt,
            "data": data,
            "store_id": store_id,
            "submitted": time.time(),
        }

        try:
            self._queue.put_nowait(task)
        except queue.Full:
            # Queue full — use heuristic immediately
            result = self._heuristic(task_type, data)
            self._results[task_id] = {"result": result, "source": "heuristic"}
            self._stats["fallback"] += 1

        self._stats["total"] += 1
        return task_id

    def get_result(self, task_id, timeout=0):
        """Get result for a task. Returns None if not ready."""
        if task_id in self._results:
            return self._results.pop(task_id)
        if timeout > 0:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if task_id in self._results:
                    return self._results.pop(task_id)
                time.sleep(0.1)
        return None

    def run_sync(self, task_type, data, store_id=""):
        """Run task synchronously. Blocks until complete or timeout."""
        role = TASK_ROLE_MAP.get(task_type, "work")
        model = MODEL_ROLES.get(role, "mistral")
        prompt = self._build_prompt(task_type, data)

        # Try model
        result = self._call_model(model, prompt)
        if result:
            self._record(task_type, data, result, "model", store_id)
            self._stats["success"] += 1
            return {"result": result, "source": model, "role": role}

        # Fallback to heuristic
        result = self._heuristic(task_type, data)
        self._record(task_type, data, result, "heuristic", store_id)
        self._stats["fallback"] += 1
        return {"result": result, "source": "heuristic", "role": role}

    # ── BACKGROUND WORKER ────────────────────────

    def _process_queue(self):
        while self._running:
            try:
                task = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                result = self._call_model(task["model"], task["prompt"])
                if result:
                    self._results[task["id"]] = {
                        "result": result, "source": task["model"]}
                    self._stats["success"] += 1
                else:
                    result = self._heuristic(task["type"], task["data"])
                    self._results[task["id"]] = {
                        "result": result, "source": "heuristic"}
                    self._stats["fallback"] += 1

                self._record(task["type"], task["data"], result,
                             task["model"], task.get("store_id", ""))
            except Exception:
                self._stats["timeout"] += 1

    # ── MODEL CALL ───────────────────────────────

    def _call_model(self, model, prompt):
        """Call Ollama model. Returns response or empty string."""
        try:
            url = "{}/api/generate".format(OLLAMA_URL)
            payload = json.dumps({
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 150, "temperature": 0.3},
            }).encode()
            req = urllib.request.Request(url, data=payload, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
                return data.get("response", "").strip()
        except Exception:
            return ""

    # ── PROMPT BUILDING ──────────────────────────

    def _build_prompt(self, task_type, data):
        """Build prompt with data context from memory."""
        # Get memory context
        context = ""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            rules = mi.get_rules(task_type.split("_")[0])
            if rules:
                rc = rules[0].get("content", {})
                if isinstance(rc, dict):
                    context = "Past experience: {}. ".format(rc.get("rule", "")[:80])
        except Exception:
            pass

        # Task-specific prompts
        if task_type == "analyze_product":
            return "{}Analyze this product briefly: {}, price ${}, cost ${}. Is it good? What to improve?".format(
                context, data.get("name", ""), data.get("price", ""), data.get("cost", ""))

        elif task_type == "write_description":
            return "{}Write a short product description (3 sentences) for: {}. Category: {}. Price: ${}.".format(
                context, data.get("name", ""), data.get("category", ""), data.get("price", ""))

        elif task_type == "generate_tags":
            return "Generate 5 SEO tags for: {}. Category: {}. Return only comma-separated tags.".format(
                data.get("name", ""), data.get("category", ""))

        elif task_type == "write_social_post":
            return "{}Write a short Instagram caption for: {}, ${}.".format(
                context, data.get("name", ""), data.get("price", ""))

        elif task_type == "write_email":
            return "Write a short welcome email (3 sentences) for store: {}. Top product: {}.".format(
                data.get("store_name", ""), data.get("product_name", ""))

        elif task_type == "score_product":
            return "Score this product 1-10: {}, price ${}, margin {}%. Just the number and reason.".format(
                data.get("name", ""), data.get("price", ""), data.get("margin", ""))

        return "{}{}".format(context, json.dumps(data)[:200])

    # ── HEURISTIC FALLBACK ───────────────────────

    @staticmethod
    def _heuristic(task_type, data):
        """Fast heuristic when model is unavailable."""
        name = data.get("name", data.get("title", "Product"))
        price = data.get("price", "")
        category = data.get("category", data.get("product_type", ""))

        if task_type == "analyze_product":
            cost = float(data.get("cost", 0))
            pr = float(price or 0)
            margin = (pr - cost) / pr if pr > 0 and cost > 0 else 0
            return "Margin {:.0%}. {}".format(margin,
                "Good profit potential." if margin > 0.4 else "Consider raising price.")

        elif task_type == "write_description":
            return "Discover the {} — premium quality {} for your needs. Great value at ${}.".format(
                name, category.lower() if category else "product", price)

        elif task_type == "generate_tags":
            words = [w.lower() for w in name.split() if len(w) > 3][:4]
            if category:
                words.append(category.lower())
            return ", ".join(words)

        elif task_type == "write_social_post":
            return "{} — ${} | Shop now! #shopify #{}".format(
                name, price, name.split()[0].lower() if name else "shop")

        elif task_type == "score_product":
            return "7/10 — standard product"

        return "Processed: {}".format(task_type)

    # ── RECORDING ────────────────────────────────

    @staticmethod
    def _record(task_type, data, result, source, store_id):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("tool_usage", {
                "tool_name": "model_{}".format(source),
                "engine_name": task_type,
                "input_size": len(str(data)),
                "output_size": len(str(result)),
                "success": bool(result),
            }, source="model_router", store_id=store_id,
                score=4.0 if source != "heuristic" else 3.0)
        except Exception:
            pass

    # ── STATS ────────────────────────────────────

    def get_stats(self):
        return {
            "available": self.is_available(),
            "queue_size": self._queue.qsize(),
            "worker_running": self._running,
            **self._stats,
            "models": MODEL_ROLES,
        }


_instance = None
def get_model_router():
    global _instance
    if _instance is None:
        _instance = ModelRouter()
    return _instance
