"""Tests for ``core.brain.api_narrative.enrich_response``.

The function is the surface-layer bridge: every API response that
flows out of ``api.server`` for a task / chain / workflow / agent /
auto-cycle endpoint passes through it. Pre-fix the API returned
opaque dicts (status + error string); the enricher adds a
human-readable ``narrative``, a ``next_action`` hint, and lifts any
``attribution`` trail into a top-3 ``attribution_summary``.

Coverage:

  1. ``_enrich`` — happy path, error path, cached path, partial /
     empty payloads.
  2. Attribution lifting — surfaces both top-level and nested.
  3. Diagnose-error mapping — known failure strings get specific
     hints; unknown ones fall through.
  4. Robustness — non-dict input passes through; internal failures
     never propagate.
"""
from __future__ import annotations


# ─── enrich_response — happy path ────────────────────────────────


class TestEnrichResponseHappyPath:

    def test_completed_status_with_choice_and_reason(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "task_id": "task_1",
            "engine": "dynamic_pricing",
            "status": "completed",
            "result": {
                "decision": "raise_10pct",
                "reason": "margin below floor",
                "confidence": 0.85,
            },
            "elapsed_seconds": 0.42,
        }
        out = enrich_response(result, task_type="dynamic_pricing")

        assert "narrative" in out
        assert "dynamic_pricing" in out["narrative"]
        assert "raise_10pct" in out["narrative"]
        assert "margin below floor" in out["narrative"]
        assert "85%" in out["narrative"]
        # Original fields preserved.
        assert out["status"] == "completed"
        assert out["task_id"] == "task_1"
        assert out["elapsed_seconds"] == 0.42

    def test_recommendations_present_suggests_apply_opt_in(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "completed",
            "result": {
                "recommendations": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}],
            },
        }
        out = enrich_response(result, task_type="discount_strategy")

        assert "next_action" in out
        assert "3 recommendations" in out["next_action"]
        assert "apply_X=True" in out["next_action"]

    def test_apply_results_present_suggests_review(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "completed",
            "result": {
                "apply_results": [
                    {"applied": True}, {"applied": False, "error": "scope"},
                ],
            },
        }
        out = enrich_response(result, task_type="search_optimization")

        assert "review 2 writeback" in out["next_action"]

    def test_cached_response_marked_in_narrative(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "completed",
            "_cached": True,
            "result": {"decision": "keep_price"},
        }
        out = enrich_response(result, task_type="dynamic_pricing")

        assert "cached" in out["narrative"]


# ─── enrich_response — error path ────────────────────────────────


class TestEnrichResponseErrorPath:

    def test_no_engine_error_suggests_registry_check(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "error",
            "error": "No engine for task_type=foo",
        }
        out = enrich_response(result, task_type="foo")

        assert "failed" in out["narrative"]
        assert "not wired to any engine" in out["narrative"]
        assert "engines.registry" in out["next_action"]

    def test_scope_error_suggests_scope_extension(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "error",
            "error": "Access denied: read_gift_cards scope missing",
        }
        out = enrich_response(result, task_type="affiliate")

        assert "missing scopes" in out["narrative"]
        assert "extend Shopify Admin scopes" in out["next_action"]

    def test_credentials_error_suggests_env_check(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "error",
            "error": "Missing Shopify credentials",
        }
        out = enrich_response(result, task_type="orders")

        assert "credentials are missing" in out["narrative"]
        assert "SHOPAI_SHOPIFY_URL" in out["next_action"]

    def test_unknown_error_falls_through_to_retry_suggestion(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "error",
            "error": "weird database lock at line 2398",
        }
        out = enrich_response(result, task_type="discount_strategy")

        assert "weird database lock" in out["narrative"]
        assert "retry" in out["next_action"]


# ─── attribution lifting ─────────────────────────────────────────


class TestAttributionSurfacing:

    def test_top_level_attribution_compacts_to_three(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "completed",
            "attribution": [
                {"source": "rules_L5", "rule_id": "r1",
                 "description": "prefer raise", "impact": 0.1},
                {"source": "memory_best_case", "rule_id": "m1",
                 "description": "raise worked before", "impact": 0.1},
                {"source": "intel_rules", "rule_id": "i1",
                 "description": "prefer raise (L2)", "impact": 0.15},
                {"source": "learned_weight", "rule_id": "h1",
                 "description": "EMA 1.4", "impact": 0.4},
            ],
            "result": {"decision": "raise_10pct"},
        }
        out = enrich_response(result, task_type="dynamic_pricing")

        assert len(out["attribution_summary"]) == 3
        first = out["attribution_summary"][0]
        assert first["source"] == "rules_L5"
        assert first["description"] == "prefer raise"
        assert first["impact"] == 0.1

    def test_nested_attribution_inside_result(self):
        from core.brain.api_narrative import enrich_response

        result = {
            "status": "completed",
            "result": {
                "decision": "lower_10pct",
                "attribution": [
                    {"source": "rules_L5", "description": "lower beat raise",
                     "impact": 0.05},
                ],
            },
        }
        out = enrich_response(result, task_type="dynamic_pricing")

        assert len(out["attribution_summary"]) == 1
        assert out["attribution_summary"][0]["description"] == "lower beat raise"

    def test_no_attribution_yields_empty_list(self):
        from core.brain.api_narrative import enrich_response

        result = {"status": "completed", "result": {"decision": "x"}}
        out = enrich_response(result, task_type="t")

        assert out["attribution_summary"] == []


# ─── partial / empty / non-dict inputs ───────────────────────────


class TestEnrichResponseRobustness:

    def test_empty_dict_passes_through_with_minimal_narrative(self):
        from core.brain.api_narrative import enrich_response

        out = enrich_response({}, task_type="t")
        # No narrative produced when there's nothing to summarise; but
        # attribution_summary and next_action are still set.
        assert "attribution_summary" in out
        assert out["attribution_summary"] == []
        # next_action is None when status missing and no recs.
        assert out["next_action"] is None

    def test_non_dict_passes_through_unchanged(self):
        from core.brain.api_narrative import enrich_response

        for payload in [None, "raw string", 42, [1, 2, 3]]:
            assert enrich_response(payload, task_type="t") == payload

    def test_internal_exception_returns_original(self, monkeypatch):
        from core.brain import api_narrative
        from core.brain.api_narrative import enrich_response

        # If anything inside the helper raises, the wrapper must
        # return the original unchanged — the API contract is
        # "narrative is best-effort; never break the response."
        def _boom(*a, **kw):
            raise RuntimeError("bang")
        monkeypatch.setattr(api_narrative, "_build_narrative", _boom)

        original = {"status": "completed", "result": {"decision": "x"}}
        out = enrich_response(original, task_type="t")
        assert out is original

    def test_unknown_status_field_yields_status_narrative(self):
        from core.brain.api_narrative import enrich_response

        out = enrich_response(
            {"status": "queued"}, task_type="dynamic_pricing",
        )
        assert "queued" in out["narrative"]
        assert "incomplete" in out["narrative"]


# ─── confidence formatting ───────────────────────────────────────


class TestConfidenceFormatting:

    def test_zero_to_one_renders_as_percent(self):
        from core.brain.api_narrative import enrich_response

        out = enrich_response(
            {"status": "completed", "confidence": 0.73,
             "result": {"decision": "x"}},
            task_type="t",
        )
        assert "73%" in out["narrative"]

    def test_zero_to_hundred_renders_as_score(self):
        from core.brain.api_narrative import enrich_response

        out = enrich_response(
            {"status": "completed", "confidence_score": 87,
             "result": {"decision": "x"}},
            task_type="t",
        )
        assert "87/100" in out["narrative"]

    def test_string_confidence_passes_through(self):
        from core.brain.api_narrative import enrich_response

        out = enrich_response(
            {"status": "completed", "confidence": "high",
             "result": {"decision": "x"}},
            task_type="t",
        )
        assert "high" in out["narrative"]
