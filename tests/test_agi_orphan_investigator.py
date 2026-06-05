"""Tests for engines.agi_orphan_investigator — W963-78."""
from __future__ import annotations

from dataclasses import dataclass, field

from engines.agi_orphan_investigator import (
    AgiOrphanInvestigatorEngine,
)
from engines.agi_orphan_investigator.investigator import (
    EngineOrphanStats,
    OrphanReport,
    _build_drill_hints,
    _build_headline,
    _build_next_action,
    _classify_suspicion,
    _median,
    investigate,
)


# ── helpers ───────────────────────────────────────────────


@dataclass
class _Orphan:
    engine: str
    action_type: str = "mint"
    store_id: str = ""
    decided_at: str = ""
    age_hours: float = 4.0
    action_id: str = ""


@dataclass
class _StoreRecon:
    store_id: str = ""
    orphans: list = field(default_factory=list)


@dataclass
class _FleetRecon:
    by_store: list = field(default_factory=list)


# ── _median ───────────────────────────────────────────────


class TestMedian:
    def test_empty(self):
        assert _median([]) == 0.0

    def test_single(self):
        assert _median([5.0]) == 5.0

    def test_odd(self):
        assert _median([1.0, 2.0, 3.0]) == 2.0

    def test_even(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


# ── _classify_suspicion ───────────────────────────────────


def _stats(count, stores_n=1):
    s = EngineOrphanStats(engine="x", orphan_count=count)
    s.stores_affected = [f"s{i}" for i in range(stores_n)]
    return s


class TestSuspicion:
    def test_low_default(self):
        assert _classify_suspicion(_stats(1)) == "low"
        assert _classify_suspicion(_stats(2)) == "low"

    def test_medium_3plus(self):
        assert _classify_suspicion(_stats(3)) == "medium"

    def test_high_10plus(self):
        assert _classify_suspicion(_stats(10)) == "high"
        assert _classify_suspicion(_stats(50)) == "high"

    def test_high_4plus_multi_store(self):
        assert _classify_suspicion(_stats(4, 2)) == "high"
        assert _classify_suspicion(_stats(5, 3)) == "high"

    def test_4plus_single_store_medium(self):
        # 4+ but only 1 store -> medium not high
        assert _classify_suspicion(_stats(4, 1)) == "medium"


# ── investigate() ─────────────────────────────────────────


class TestInvestigate:
    def test_no_fleet_data(self):
        r = investigate(
            fleet_report_override=_FleetRecon(),
        )
        assert r.total_orphan_count == 0
        assert r.by_engine == []
        assert "No orphan" in r.headline

    def test_single_store_single_engine(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[
                    _Orphan(engine="loyalty"),
                    _Orphan(engine="loyalty"),
                    _Orphan(engine="loyalty"),
                ],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        assert r.total_orphan_count == 3
        assert r.distinct_engines == 1
        assert r.by_engine[0].engine == "loyalty"
        assert r.by_engine[0].orphan_count == 3
        # 3 orphans single store -> medium
        assert r.by_engine[0].suspicion == "medium"

    def test_sort_by_count_desc(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[
                    _Orphan(engine="affiliate"),
                    _Orphan(engine="loyalty"),
                    _Orphan(engine="loyalty"),
                    _Orphan(engine="loyalty"),
                ],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        assert r.by_engine[0].engine == "loyalty"
        assert r.by_engine[1].engine == "affiliate"

    def test_cross_store_aggregation(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[_Orphan(engine="loyalty")],
            ),
            _StoreRecon(
                store_id="s2",
                orphans=[_Orphan(engine="loyalty")],
            ),
            _StoreRecon(
                store_id="s3",
                orphans=[_Orphan(engine="loyalty")],
            ),
            _StoreRecon(
                store_id="s4",
                orphans=[_Orphan(engine="loyalty")],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        # 4+ orphans across 4 stores -> high
        assert r.by_engine[0].suspicion == "high"
        assert (
            len(r.by_engine[0].stores_affected) == 4
        )

    def test_per_store_stats(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[
                    _Orphan(engine="loyalty"),
                    _Orphan(engine="affiliate"),
                ],
            ),
            _StoreRecon(
                store_id="s2",
                orphans=[
                    _Orphan(engine="loyalty"),
                ],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        # s1 has more orphans -> sorted first
        assert r.by_store[0].store_id == "s1"
        assert r.by_store[0].orphan_count == 2
        assert r.by_store[0].distinct_engines == 2
        assert r.by_store[1].store_id == "s2"
        assert r.by_store[1].distinct_engines == 1

    def test_action_type_aggregation(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[
                    _Orphan(
                        engine="loyalty",
                        action_type="mint",
                    ),
                    _Orphan(
                        engine="loyalty",
                        action_type="renew",
                    ),
                    _Orphan(
                        engine="loyalty",
                        action_type="mint",
                    ),
                ],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        types = r.by_engine[0].action_types
        assert "mint" in types
        assert "renew" in types
        assert len(types) == 2

    def test_median_age_computed(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[
                    _Orphan(
                        engine="loyalty", age_hours=1.0,
                    ),
                    _Orphan(
                        engine="loyalty", age_hours=3.0,
                    ),
                    _Orphan(
                        engine="loyalty", age_hours=5.0,
                    ),
                ],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        assert r.by_engine[0].median_age_hours == 3.0

    def test_unknown_engine_falls_through(self):
        fleet = _FleetRecon(by_store=[
            _StoreRecon(
                store_id="s1",
                orphans=[_Orphan(engine="")],
            ),
        ])
        r = investigate(fleet_report_override=fleet)
        assert r.by_engine[0].engine == "(unknown)"


# ── headline / next_action / drill_hints ──────────────────


class TestHeadline:
    def test_clean(self):
        r = OrphanReport(days=7, attribution_window_hours=48.0)
        assert "No orphan" in _build_headline(r)

    def test_with_top_engine(self):
        r = OrphanReport(
            days=7, attribution_window_hours=48.0,
            total_orphan_count=10,
            distinct_engines=2,
            by_engine=[
                EngineOrphanStats(
                    engine="loyalty",
                    orphan_count=8, suspicion="high",
                ),
                EngineOrphanStats(
                    engine="affiliate",
                    orphan_count=2, suspicion="low",
                ),
            ],
        )
        h = _build_headline(r)
        assert "10 orphan" in h
        assert "loyalty" in h
        assert "high-suspicion" in h


class TestNextAction:
    def test_clean(self):
        r = OrphanReport(days=7, attribution_window_hours=48.0)
        n = _build_next_action(r)
        assert "Clean" in n

    def test_with_high_suspicion(self):
        r = OrphanReport(
            days=7, attribution_window_hours=48.0,
            total_orphan_count=5,
            by_engine=[
                EngineOrphanStats(
                    engine="loyalty",
                    orphan_count=5, suspicion="high",
                ),
            ],
        )
        n = _build_next_action(r)
        assert "high-suspicion" in n
        assert "loyalty" in n

    def test_low_only(self):
        r = OrphanReport(
            days=7, attribution_window_hours=48.0,
            total_orphan_count=2,
            by_engine=[
                EngineOrphanStats(
                    engine="x",
                    orphan_count=2, suspicion="low",
                ),
            ],
        )
        n = _build_next_action(r)
        assert "low" in n


class TestDrillHints:
    def test_clean_empty(self):
        r = OrphanReport(days=7, attribution_window_hours=48.0)
        assert _build_drill_hints(r) == []

    def test_high_suspicion_emits_pulse_hint(self):
        r = OrphanReport(
            days=7, attribution_window_hours=48.0,
            by_engine=[
                EngineOrphanStats(
                    engine="loyalty",
                    orphan_count=10, suspicion="high",
                ),
            ],
        )
        hints = _build_drill_hints(r)
        assert any(
            "pulse loyalty" in h for h in hints
        )
        assert any(
            "engine alerts" in h for h in hints
        )

    def test_widen_window_hint(self):
        r = OrphanReport(
            days=7, attribution_window_hours=48.0,
            by_engine=[
                EngineOrphanStats(
                    engine="loyalty",
                    orphan_count=10, suspicion="high",
                    median_age_hours=72.0,
                ),
            ],
        )
        hints = _build_drill_hints(r)
        assert any(
            "wider attribution window" in h
            for h in hints
        )


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiOrphanInvestigatorEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiOrphanInvestigatorEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiOrphanInvestigatorEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiOrphanInvestigatorEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiOrphanInvestigatorEngine().run({})
        assert (
            r["meta"]["engine"]
            == "agi_orphan_investigator"
        )

    def test_invalid_days_falls_back(self):
        r = AgiOrphanInvestigatorEngine().run({
            "data": {"days": "abc"},
        })
        assert r["data"]["days"] == 7
