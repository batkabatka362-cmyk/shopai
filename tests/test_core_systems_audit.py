"""Tests for the audit-pass-6 fixes across core/system + intelligence_cycle.

  1. intelligence_cycle.run() built attach_result payload as
     `{score, rating, executed, **execution_result}` — the spread
     came AFTER the literal keys so a buggy action_fn returning
     `{"score": 0, ...}` would silently overwrite the evaluator's
     score in the data architecture.
  2. intelligence_cycle stages 7, 8, 9, 10 had no isolation. A
     failure in capture_result, attach_result, learning, or
     update_memory aborted the cycle before the remaining stages
     could run, leaving partial state behind.
  3. SharedMemory.exists() detected expired entries but didn't
     remove them, so get_stats() over-counted.
  4. AdaptiveSkills.record_outcome silently no-op'd when the
     skill name was unknown, hiding caller typos.
"""
import time

import pytest


# ── intelligence_cycle dict-spread + isolation ───────────────


def _ic_with_stubbed_backends():
    """Build an IntelligenceCycle whose backends are simple recording
    stubs so tests can drive specific scenarios without sqlite."""
    from core.intelligence_cycle import IntelligenceCycle

    class _Arch:
        def __init__(self):
            self.actions = []
            self.results = []
            self.fail_attach = False
            self.fail_record = False

        def record_action(self, **kwargs):
            if self.fail_record:
                raise RuntimeError("data arch down")
            self.actions.append(kwargs)

        def attach_result(self, action_id, payload, score):
            if self.fail_attach:
                raise RuntimeError("attach broken")
            self.results.append({
                "action_id": action_id,
                "payload": payload,
                "score": score,
            })

    class _Mem:
        def _extract_features(self, category, data):
            return {"f": "x"}

        def retrieve_for_decision(self, category):
            return {
                "best_events": [], "patterns": [], "rules": [],
                "strategies": [], "failures": [], "total_memories": 0,
            }

        def create_from_decision(self, *args, **kwargs):
            return 1

        def record_failure(self, *args, **kwargs):
            return 1

    ic = IntelligenceCycle()
    ic._data_arch = _Arch()
    ic._memory_intel = _Mem()
    return ic


class TestAttachResultDictSpread:
    def test_evaluator_score_wins_over_action_fn_score(self):
        """Regression: if action_fn returns {"score": 0}, the
        cycle previously persisted that score in attach_result
        instead of the evaluator's score. The literal keys must
        win over the spread now."""
        ic = _ic_with_stubbed_backends()

        def action_fn(decision):
            # Buggy/competing action_fn returning a "score" key
            return {"score": 0, "rating": "bogus", "executed": False, "extra": "x"}

        ic.run("pricing", {"raw": 1}, action_fn=action_fn)
        # The recorded payload's "score" must be the evaluator score,
        # not the 0 returned by the action_fn.
        assert len(ic._data_arch.results) == 1
        attached = ic._data_arch.results[0]
        # Evaluator default score is 3.0 (neutral). Whatever it
        # picked, it must NOT be 0 (the action_fn lie).
        assert attached["payload"]["score"] != 0
        assert attached["payload"]["rating"] != "bogus"
        # Original action_fn fields that don't collide are preserved.
        assert attached["payload"]["extra"] == "x"

    def test_normal_action_fn_works_unchanged(self):
        ic = _ic_with_stubbed_backends()

        def action_fn(decision):
            return {"summary": "ok"}

        ic.run("pricing", {"raw": 1}, action_fn=action_fn)
        attached = ic._data_arch.results[0]
        assert attached["payload"]["summary"] == "ok"
        assert attached["payload"]["executed"] is True


class TestIntelligenceCycleStageIsolation:
    def test_capture_result_failure_does_not_abort_cycle(self):
        ic = _ic_with_stubbed_backends()
        ic._data_arch.fail_record = True

        result = ic.run("pricing", {"raw": 1})
        # Cycle still completes, returns a result, captures the
        # error in stages.result, and runs subsequent stages.
        assert "stages" in result
        assert result["stages"]["result"]["captured"] is False
        assert "evaluation" in result["stages"]
        assert "learning" in result["stages"]
        assert "update" in result["stages"]

    def test_attach_result_failure_does_not_abort_cycle(self):
        ic = _ic_with_stubbed_backends()
        ic._data_arch.fail_attach = True

        result = ic.run("pricing", {"raw": 1})
        # Evaluation stage records the attach_error but cycle
        # still reaches learning + update.
        assert "attach_error" in result["stages"]["evaluation"]
        assert "learning" in result["stages"]
        assert "update" in result["stages"]

    def test_learning_failure_does_not_abort_cycle(self, monkeypatch):
        ic = _ic_with_stubbed_backends()
        monkeypatch.setattr(
            ic, "_learn",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("learn boom")),
        )
        result = ic.run("pricing", {"raw": 1})
        assert "error" in result["stages"]["learning"]
        assert "learn boom" in result["stages"]["learning"]["error"]
        # Update phase still ran
        assert "update" in result["stages"]

    def test_update_memory_failure_does_not_abort_cycle(self, monkeypatch):
        ic = _ic_with_stubbed_backends()
        monkeypatch.setattr(
            ic, "_update_memory",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("update boom")),
        )
        result = ic.run("pricing", {"raw": 1})
        assert "error" in result["stages"]["update"]
        # Cycle still returned successfully and recorded duration
        assert "duration_s" in result


# ── SharedMemory.exists() expired entry leak ─────────────────


class TestSharedMemoryExistsLeak:
    def test_expired_entry_dropped_on_exists_check(self):
        from core.system.shared_memory import SharedMemory
        sm = SharedMemory()
        sm.put("cache", "k", "v", ttl_seconds=1)
        # Force expiry
        sm._store["cache"]["k"]["expires_at"] = time.time() - 1

        assert sm.exists("cache", "k") is False
        # The entry must be gone from the store, not just hidden.
        assert "k" not in sm._store["cache"]

    def test_get_stats_no_longer_counts_expired(self):
        from core.system.shared_memory import SharedMemory
        sm = SharedMemory()
        sm.put("cache", "k1", "v", ttl_seconds=1)
        sm.put("cache", "k2", "v", ttl_seconds=600)
        sm._store["cache"]["k1"]["expires_at"] = time.time() - 1

        # Trigger eviction via exists()
        sm.exists("cache", "k1")
        stats = sm.get_stats()
        assert stats["namespaces"]["cache"] == 1
        assert stats["total_entries"] == 1

    def test_non_expired_still_returns_true(self):
        from core.system.shared_memory import SharedMemory
        sm = SharedMemory()
        sm.put("cache", "k", "v", ttl_seconds=600)
        assert sm.exists("cache", "k") is True
        assert "k" in sm._store["cache"]

    def test_no_ttl_entry_never_expires(self):
        from core.system.shared_memory import SharedMemory
        sm = SharedMemory()
        sm.put("cache", "k", "v")  # ttl=0 default
        assert sm.exists("cache", "k") is True


# ── AdaptiveSkills.record_outcome unknown skill ──────────────


class TestAdaptiveSkillsRecordOutcomeUnknown:
    def test_unknown_skill_returns_false(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        assert skills.record_outcome("does_not_exist", success=True) is False

    def test_unknown_skill_logs_warning(self, monkeypatch):
        from core.system import adaptive_skills as mod
        skills = mod.AdaptiveSkills()
        warnings = []

        def _capture(msg, *args, **kwargs):
            warnings.append(msg % args if args else msg)

        monkeypatch.setattr(mod.logger, "warning", _capture)
        skills.record_outcome("typo_skill", success=True)
        assert any("typo_skill" in w for w in warnings)
        assert any("unknown skill" in w.lower() for w in warnings)

    def test_known_skill_returns_true_and_records(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        # competitive_pricing is in the default set
        assert skills.record_outcome("competitive_pricing", success=True) is True
        skill = skills.get_skill("competitive_pricing")
        assert skill.uses == 1
        assert skill.successes == 1
