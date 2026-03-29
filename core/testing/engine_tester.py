"""EngineTester — runs test suites against engines."""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from engines.registry import get_engine, is_registered
from engines.base.engine_types import EngineInput

logger = get_logger("testing.engine_tester")


class EngineTester:
    """Runs test cases against engines and reports results."""

    def test_engine(self, engine_name: str, test_cases: list[dict[str, Any]]) -> dict[str, Any]:
        """Run test cases against an engine."""
        if not is_registered(engine_name):
            return {"engine": engine_name, "error": "not registered", "passed": 0, "failed": 0}

        results = []
        for tc in test_cases:
            result = self._run_case(engine_name, tc)
            results.append(result)

        passed = sum(1 for r in results if r["passed"])
        failed = len(results) - passed

        return {
            "engine": engine_name,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / len(results), 4) if results else 0,
            "results": results,
        }

    def smoke_test(self, engine_name: str) -> dict[str, Any]:
        """Quick smoke test: can engine load and run without crashing?"""
        start = time.monotonic()
        try:
            engine = get_engine(engine_name)
            # Run with minimal data
            inp = EngineInput(
                task_id=f"smoke_{engine_name}",
                engine_name=engine_name,
                data={f: {} for f in engine.required_input_fields},
            )
            output = engine.run(inp)
            elapsed = time.monotonic() - start
            return {
                "engine": engine_name,
                "status": "pass",
                "engine_status": output.status.value,
                "elapsed_ms": round(elapsed * 1000, 2),
                "steps_run": len(output.steps),
            }
        except Exception as exc:
            return {"engine": engine_name, "status": "crash", "error": str(exc), "elapsed_ms": round((time.monotonic() - start) * 1000, 2)}

    def smoke_test_batch(self, engine_names: list[str]) -> dict[str, Any]:
        """Smoke test multiple engines."""
        results = [self.smoke_test(name) for name in engine_names]
        passed = sum(1 for r in results if r["status"] == "pass")
        return {
            "total": len(results),
            "passed": passed,
            "crashed": len(results) - passed,
            "results": results,
        }

    def _run_case(self, engine_name: str, test_case: dict[str, Any]) -> dict[str, Any]:
        """Run a single test case."""
        tc_name = test_case.get("name", "unnamed")
        input_data = test_case.get("input", {})
        expect_status = test_case.get("expect_status", "completed")
        expect_fields = test_case.get("expect_output_fields", [])

        start = time.monotonic()
        try:
            engine = get_engine(engine_name)
            inp = EngineInput(task_id=f"test_{tc_name}", engine_name=engine_name, data=copy.deepcopy(input_data))
            output = engine.run(inp)
            elapsed = time.monotonic() - start

            # Check status
            actual_status = output.status.value
            if isinstance(expect_status, list):
                status_ok = actual_status in expect_status
            else:
                status_ok = actual_status == expect_status

            # Check output fields
            fields_ok = True
            missing = []
            if expect_fields and output.result:
                for field in expect_fields:
                    if field not in output.result:
                        fields_ok = False
                        missing.append(field)

            passed = status_ok and fields_ok

            return {
                "name": tc_name,
                "passed": passed,
                "status": actual_status,
                "expected_status": expect_status,
                "status_ok": status_ok,
                "fields_ok": fields_ok,
                "missing_fields": missing,
                "elapsed_ms": round(elapsed * 1000, 2),
                "error": output.error,
            }

        except Exception as exc:
            return {
                "name": tc_name,
                "passed": False,
                "status": "crash",
                "error": str(exc),
                "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
            }
