"""Tests for audit-pass-21 fixes in core/orchestrator/priority_engine.

  1. Every URGENCY_RULES lambda used `s.get("section", {}).get(...)`.
     `.get(k, default)` returns the literal default ONLY when the
     key is missing — if the key is present with a None value
     (which happens during initial state or after a partial
     snapshot update failure), `.get` returns None and the next
     chained `.get` crashes with AttributeError.
  2. The marketing rule used `len(s.get("events", []))` — same
     bug class with `len(None)` raising TypeError.
  3. compute() called every rule lambda without try/except. A
     single buggy / breaking rule killed the entire priority
     computation, taking out the orchestrator's whole priority
     phase.
"""
import pytest


def _engine():
    from core.orchestrator.priority_engine import PriorityEngine
    return PriorityEngine()


# ── Defensive None handling in URGENCY_RULES ────────────────


class TestNoneSectionHandling:
    def test_inventory_section_none_no_crash(self):
        """Regression: previously `s.get("inventory", {}).get(
        "out_of_stock_count", 0)` crashed when inventory was
        present with value None."""
        eng = _engine()
        priorities = eng.compute({"inventory": None, "financial": None})
        # Did not crash; returned a list of priorities all at "normal"
        assert isinstance(priorities, list)
        assert all(p["urgency"] == "normal" for p in priorities)

    def test_all_sections_none(self):
        eng = _engine()
        priorities = eng.compute({
            "inventory": None,
            "financial": None,
            "customers": None,
            "marketing": None,
            "events": None,
            "health": None,
        })
        assert all(p["urgency"] == "normal" for p in priorities)

    def test_events_none_does_not_crash(self):
        """Regression: previously `len(s.get("events", []))`
        crashed when events was None (TypeError on len(None))."""
        eng = _engine()
        priorities = eng.compute({"events": None})
        marketing = next(p for p in priorities if p["domain"] == "marketing")
        # No events → marketing stays normal
        assert marketing["urgency"] == "normal"

    def test_top_level_situation_none(self):
        """compute(None) should return defaulted priorities, not crash."""
        eng = _engine()
        priorities = eng.compute(None)
        assert len(priorities) == len(
            __import__("core.orchestrator.priority_engine", fromlist=["URGENCY_RULES"]).URGENCY_RULES
        )

    def test_top_level_situation_string(self):
        eng = _engine()
        priorities = eng.compute("not a dict")
        assert isinstance(priorities, list)


# ── Per-rule try/except isolation ───────────────────────────


class TestPerRuleIsolation:
    def test_broken_rule_does_not_crash_other_domains(self, monkeypatch):
        """Inject a broken rule and verify the other domains still
        compute correctly."""
        from core.orchestrator.priority_engine import URGENCY_RULES
        from core.orchestrator.priority_engine import PriorityEngine

        original_inv_critical = URGENCY_RULES["inventory"]["critical"]

        def _boom(s):
            raise RuntimeError("inventory rule exploded")

        monkeypatch.setitem(URGENCY_RULES["inventory"], "critical", _boom)
        try:
            eng = PriorityEngine()
            priorities = eng.compute({
                "inventory": {"out_of_stock_count": 5},
                "customers": {"churn_risk_pct": 80},
            })
            # The broken inventory critical was skipped → falls
            # through to "high" / "medium" / normal. The customers
            # critical rule still fired.
            customers = next(p for p in priorities if p["domain"] == "customers")
            assert customers["urgency"] == "critical"
        finally:
            URGENCY_RULES["inventory"]["critical"] = original_inv_critical

    def test_has_critical_handles_broken_rule(self, monkeypatch):
        from core.orchestrator.priority_engine import URGENCY_RULES, PriorityEngine
        original = URGENCY_RULES["financial"]["critical"]

        def _boom(s):
            raise RuntimeError("kaboom")

        monkeypatch.setitem(URGENCY_RULES["financial"], "critical", _boom)
        try:
            eng = PriorityEngine()
            # Customers has a real critical → has_critical = True
            assert eng.has_critical({"customers": {"churn_risk_pct": 90}}) is True
            # Nothing critical → False (broken rule treated as not-fired)
            assert eng.has_critical({}) is False
        finally:
            URGENCY_RULES["financial"]["critical"] = original

    def test_broken_rule_logs_warning(self, monkeypatch):
        from core.orchestrator.priority_engine import URGENCY_RULES, PriorityEngine
        import core.orchestrator.priority_engine as pe_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            pe_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        original = URGENCY_RULES["inventory"]["critical"]
        monkeypatch.setitem(
            URGENCY_RULES["inventory"], "critical",
            lambda s: (_ for _ in ()).throw(RuntimeError("inv kaboom")),
        )
        try:
            PriorityEngine().compute({"inventory": {}})
            assert any("inventory" in w and "kaboom" in w for w in warnings)
        finally:
            URGENCY_RULES["inventory"]["critical"] = original


# ── Regression: real rules still fire correctly ─────────────


class TestRealRulesStillWork:
    def test_inventory_critical_fires(self):
        eng = _engine()
        priorities = eng.compute({"inventory": {"out_of_stock_count": 3}})
        inv = next(p for p in priorities if p["domain"] == "inventory")
        assert inv["urgency"] == "critical"

    def test_financial_high_fires_on_grade_d(self):
        eng = _engine()
        priorities = eng.compute({"financial": {"health_grade": "D"}})
        fin = next(p for p in priorities if p["domain"] == "financial")
        assert fin["urgency"] == "high"

    def test_customers_critical_at_70pct(self):
        eng = _engine()
        priorities = eng.compute({"customers": {"churn_risk_pct": 80}})
        cust = next(p for p in priorities if p["domain"] == "customers")
        assert cust["urgency"] == "critical"

    def test_priorities_sorted_by_score_desc(self):
        eng = _engine()
        priorities = eng.compute({
            "inventory": {"out_of_stock_count": 5},  # critical
            "customers": {"churn_risk_pct": 35},     # medium
            "financial": {"health_grade": "B"},      # normal
        })
        scores = [p["score"] for p in priorities]
        assert scores == sorted(scores, reverse=True)
