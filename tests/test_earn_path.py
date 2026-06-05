"""Tests for engines.earn_path — W963-88."""
from __future__ import annotations

from unittest.mock import patch

from engines.earn_path import EarnPathEngine
from engines.earn_path.guide import (
    Stage,
    _build_stages,
    build_path,
)


# ── _build_stages ─────────────────────────────────────────


class TestBuildStages:
    def test_has_8_stages(self):
        stages = _build_stages()
        assert len(stages) == 8

    def test_each_carries_command(self):
        stages = _build_stages()
        for s in stages:
            assert s.cli_command
            assert s.title
            assert s.rationale

    def test_progression_order(self):
        stages = _build_stages()
        names = [s.name for s in stages]
        assert names == [
            "config_env",
            "notify_webhook",
            "set_niches",
            "seed_catalog",
            "schedule_cron",
            "first_cycle",
            "enable_phase5",
            "earning",
        ]


# ── build_path ────────────────────────────────────────────


# Probe function names in the guide module.
_PROBE_FN_NAMES = (
    "_config_env_done",
    "_notify_webhook_done",
    "_niches_done",
    "_catalog_seeded",
    "_cron_scheduled",
    "_first_cycle_ran",
    "_phase5_enabled",
    "_is_earning",
)


def _patch_all_probes(values):
    """Build a list of patch contexts, one per probe.
    values is a tuple matching _PROBE_FN_NAMES order."""
    return [
        patch(
            f"engines.earn_path.guide.{name}",
            return_value=val,
        )
        for name, val in zip(_PROBE_FN_NAMES, values)
    ]


class TestBuildPath:
    def test_all_undone_first_stage_next(self):
        patches = _patch_all_probes(
            (False,) * len(_PROBE_FN_NAMES),
        )
        for p in patches:
            p.start()
        try:
            r = build_path()
        finally:
            for p in patches:
                p.stop()
        assert r.completed_count == 0
        assert r.pct_complete == 0.0
        assert r.next_stage == "config_env"
        assert "earn-config" in r.next_command

    def test_first_done_advances_next(self):
        patches = [
            patch(
                "engines.earn_path.guide._config_env_done",
                return_value=True,
            ),
            patch(
                "engines.earn_path.guide."
                "_notify_webhook_done",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._niches_done",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._catalog_seeded",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._cron_scheduled",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide."
                "_first_cycle_ran",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._phase5_enabled",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._is_earning",
                return_value=False,
            ),
        ]
        for p in patches:
            p.start()
        try:
            r = build_path()
        finally:
            for p in patches:
                p.stop()
        assert r.completed_count == 1
        assert r.next_stage == "notify_webhook"

    def test_all_done_no_next(self):
        patches = [
            patch(
                f"engines.earn_path.guide.{fn}",
                return_value=True,
            )
            for fn in (
                "_config_env_done",
                "_notify_webhook_done",
                "_niches_done",
                "_catalog_seeded",
                "_cron_scheduled",
                "_first_cycle_ran",
                "_phase5_enabled",
                "_is_earning",
            )
        ]
        for p in patches:
            p.start()
        try:
            r = build_path()
        finally:
            for p in patches:
                p.stop()
        assert r.completed_count == 8
        assert r.pct_complete == 100.0
        assert r.next_stage is None
        assert "earning" in r.headline

    def test_out_of_order_done_still_marked(self):
        """If stage 4 is done but stages 2-3 aren't, walk
        still marks stage 2 as 'next' and stage 4 as 'done'."""
        patches = [
            patch(
                "engines.earn_path.guide._config_env_done",
                return_value=True,
            ),
            patch(
                "engines.earn_path.guide."
                "_notify_webhook_done",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._niches_done",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._catalog_seeded",
                return_value=True,  # out-of-order
            ),
            patch(
                "engines.earn_path.guide._cron_scheduled",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide."
                "_first_cycle_ran",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._phase5_enabled",
                return_value=False,
            ),
            patch(
                "engines.earn_path.guide._is_earning",
                return_value=False,
            ),
        ]
        for p in patches:
            p.start()
        try:
            r = build_path()
        finally:
            for p in patches:
                p.stop()
        stages_by_name = {
            s["name"] if isinstance(s, dict) else s.name: s
            for s in r.stages
        }
        assert (
            stages_by_name["config_env"].status == "done"
        )
        assert (
            stages_by_name["notify_webhook"].status
            == "next"
        )
        assert (
            stages_by_name["seed_catalog"].status == "done"
        )
        # set_niches comes BEFORE seed_catalog but isn't
        # done; since next is taken, it stays pending
        assert (
            stages_by_name["set_niches"].status == "pending"
        )
        # Completed count includes the out-of-order done
        assert r.completed_count == 2


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = EarnPathEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = EarnPathEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = EarnPathEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = EarnPathEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = EarnPathEngine().run({})
        assert r["meta"]["engine"] == "earn_path"

    def test_data_has_progress(self):
        r = EarnPathEngine().run({})
        d = r["data"]
        assert "stages" in d
        assert "completed_count" in d
        assert "pct_complete" in d
        assert "headline" in d
