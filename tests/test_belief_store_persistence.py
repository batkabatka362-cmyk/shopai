"""Wave 6 #4: BeliefStore disk snapshot + reload.

Wave 2 #2 landed the :class:`core.mentality.BeliefStore` with an
explicit note that persistence was out of scope and would come
later. Wave 6 #2/#3 then made the store load-bearing: every
executed action feeds it, and :meth:`JudgmentAdvisor.evaluate`
reads the posterior before letting a decision through. Without
persistence, a restart loses all accumulated learning and the
gate falls back to uniform priors.

Wave 6 #4 adds an optional ``persist_path`` to ``BeliefStore``.
On construction the store loads any existing snapshot; on every
``observe`` call it atomically rewrites the file so a crash can
lose at most one observation. The format is a flat JSON dict
``{key: {alpha, beta}}`` — derived fields (``mean``, ``n``)
recompute trivially and are not stored.

These tests drive the store directly so we don't have to boot
the advisor.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.mentality import BeliefStore


# ---------------------------------------------------------------------------
# Bring-up
# ---------------------------------------------------------------------------


def test_no_persist_path_stays_in_memory_only(tmp_path: Path):
    """Default construction must preserve legacy behaviour:
    no file created, no file read."""
    store = BeliefStore()
    store.observe("k", True)
    # tmp_path should be completely empty — we passed no path
    assert list(tmp_path.iterdir()) == []
    assert store.persist_path is None


def test_persist_path_creates_file_on_first_observe(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    store = BeliefStore(persist_path=path)
    assert not path.exists()  # no write before first observation
    store.observe("shopify::pricing", True)
    assert path.exists()
    raw = json.loads(path.read_text())
    assert "shopify::pricing" in raw
    assert raw["shopify::pricing"]["alpha"] == 2.0  # prior 1 + 1 success
    assert raw["shopify::pricing"]["beta"] == 1.0


def test_persist_path_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "beliefs.json"
    store = BeliefStore(persist_path=path)
    store.observe("x", True)
    assert path.exists()


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_all_parameters(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    s1 = BeliefStore(persist_path=path)
    for _ in range(7):
        s1.observe("a::b", True)
    for _ in range(3):
        s1.observe("a::b", False)
    s1.observe("c::d", False)

    # Fresh store on the same file reloads the data
    s2 = BeliefStore(persist_path=path)
    assert set(s2.keys()) == {"a::b", "c::d"}
    belief = s2.get("a::b")
    assert belief is not None
    # alpha = prior 1 + 7 successes = 8
    # beta  = prior 1 + 3 failures  = 4
    assert belief.alpha == 8.0
    assert belief.beta == 4.0
    assert s2.mean("a::b") == pytest.approx(8.0 / 12.0)


def test_observe_is_atomic_write(tmp_path: Path):
    """Every observation must rewrite the snapshot — not append."""
    path = tmp_path / "beliefs.json"
    store = BeliefStore(persist_path=path)
    store.observe("k", True)
    store.observe("k", True)
    raw = json.loads(path.read_text())
    assert raw["k"]["alpha"] == 3.0  # 1 + 2
    assert raw["k"]["beta"] == 1.0
    # File is single valid JSON object — not JSONL
    assert path.read_text().count("\n") <= 1


def test_explicit_save_persists_current_state(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    store = BeliefStore(persist_path=path)
    store.observe("k", True)
    # Mutate directly (bypassing observe), then save
    belief = store.get("k")
    belief.alpha = 50.0
    store.save()
    raw = json.loads(path.read_text())
    assert raw["k"]["alpha"] == 50.0


def test_save_noop_without_persist_path(tmp_path: Path):
    """Explicit save on a non-persistent store is a silent no-op
    — not an error."""
    store = BeliefStore()
    store.save()  # must not raise
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Reset keeps disk in sync
# ---------------------------------------------------------------------------


def test_reset_all_clears_disk(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    store = BeliefStore(persist_path=path)
    store.observe("k", True)
    store.reset()
    raw = json.loads(path.read_text())
    assert raw == {}


def test_reset_one_key_updates_disk(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    store = BeliefStore(persist_path=path)
    store.observe("keep", True)
    store.observe("drop", True)
    store.reset("drop")
    raw = json.loads(path.read_text())
    assert "keep" in raw
    assert "drop" not in raw


# ---------------------------------------------------------------------------
# Load degradation — bad files never crash construction
# ---------------------------------------------------------------------------


def test_missing_file_loads_empty(tmp_path: Path):
    path = tmp_path / "does_not_exist.json"
    store = BeliefStore(persist_path=path)
    assert store.keys() == []


def test_malformed_json_falls_back_to_empty(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    path.write_text("not-json-at-all{{{")
    store = BeliefStore(persist_path=path)
    assert store.keys() == []
    # And can still observe — writing a fresh snapshot
    store.observe("k", True)
    raw = json.loads(path.read_text())
    assert "k" in raw


def test_non_dict_root_ignored(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    path.write_text("[]")  # valid JSON but wrong shape
    store = BeliefStore(persist_path=path)
    assert store.keys() == []


def test_partial_bad_rows_are_skipped_good_rows_loaded(tmp_path: Path):
    path = tmp_path / "beliefs.json"
    path.write_text(json.dumps({
        "good":             {"alpha": 5.0, "beta": 2.0},
        "bad_alpha_string": {"alpha": "x", "beta": 2.0},
        "bad_not_dict":     "scalar",
        "bad_negative":     {"alpha": -1.0, "beta": 2.0},
        "bad_zero":         {"alpha": 0.0, "beta": 2.0},
        "missing_beta":     {"alpha": 5.0},
        "good2":            {"alpha": 1.5, "beta": 3.5},
    }))
    store = BeliefStore(persist_path=path)
    assert set(store.keys()) == {"good", "good2"}
    assert store.get("good").alpha == 5.0
    assert store.get("good2").beta == 3.5


# ---------------------------------------------------------------------------
# Custom prior still applies when loading
# ---------------------------------------------------------------------------


def test_custom_prior_preserved_across_restart(tmp_path: Path):
    """Custom priors are stored implicitly: the first observation
    from each belief includes the prior, so reloading gives you
    the post-prior state. New keys after reload still use the
    current prior."""
    path = tmp_path / "beliefs.json"
    s1 = BeliefStore(persist_path=path, prior_alpha=2.0, prior_beta=2.0)
    s1.observe("existing", True)  # alpha=3, beta=2

    s2 = BeliefStore(persist_path=path, prior_alpha=5.0, prior_beta=5.0)
    # Existing key uses the value frozen on disk
    assert s2.get("existing").alpha == 3.0
    assert s2.get("existing").beta == 2.0
    # New key uses the new prior
    s2.observe("fresh", False)
    assert s2.get("fresh").alpha == 5.0  # new prior 5 + 0 successes
    assert s2.get("fresh").beta == 6.0   # new prior 5 + 1 failure


# ---------------------------------------------------------------------------
# Concurrent access — locking still holds with persistence enabled
# ---------------------------------------------------------------------------


def test_many_observations_from_multiple_threads(tmp_path: Path):
    import threading
    path = tmp_path / "beliefs.json"
    store = BeliefStore(persist_path=path)
    threads = []

    def _spam():
        for _ in range(50):
            store.observe("k", True)

    for _ in range(4):
        t = threading.Thread(target=_spam)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    # 200 total observations, all successes → alpha = 201, beta = 1
    belief = store.get("k")
    assert belief.alpha == 201.0
    assert belief.beta == 1.0
    # And the disk file matches
    raw = json.loads(path.read_text())
    assert raw["k"]["alpha"] == 201.0


# ---------------------------------------------------------------------------
# Observability via JudgmentAdvisor — beliefs survive a simulated restart
# ---------------------------------------------------------------------------


def test_advisor_reload_restores_learning(tmp_path: Path):
    """End-to-end: feed outcomes through an advisor, create a
    fresh advisor on the same file, and confirm evaluate() sees
    the accumulated data."""
    from core.judgment.judgment_advisor import JudgmentAdvisor

    path = tmp_path / "beliefs.json"
    advisor1 = JudgmentAdvisor(belief_store=BeliefStore(persist_path=path))
    for _ in range(6):
        advisor1.update_belief("shopify::pricing.update", False)

    advisor2 = JudgmentAdvisor(belief_store=BeliefStore(persist_path=path))
    decision = {
        "action":           "adjust pricing",
        "confidence_score": 85,
        "target":           "shopify",
        "action_type":      "pricing.update",
    }
    situation = {
        "financial":   {"health_grade": "A", "critical_alerts": 0},
        "health":      {"overall_grade": "A"},
        "competitive": {"alerts": []},
        "customers":   {"churn_risk_pct": 0},
        "inventory":   {"stockout_risk": False},
        "events":      [],
    }
    result = advisor2.evaluate(decision, situation)
    belief_check = next(
        c for c in result["checks"] if c["check"] == "belief_posterior"
    )
    # weight active (evidence reloaded) and risk elevated
    assert belief_check["weight"] == 0.15
    assert belief_check["risk"] > 0.5
