"""Autopilot loop daemon tests."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from scripts import autopilot_loop as al


def _make_autopilot(
    launches: int = 1, successful: int = 1,
    raise_exc: bool = False,
):
    pilot = MagicMock()
    run = MagicMock()
    run.launches = [MagicMock() for _ in range(launches)]
    run.successful_launches = successful
    if raise_exc:
        pilot.run.side_effect = RuntimeError("oops")
    else:
        pilot.run.return_value = run
    return pilot


def _make_learner(proposals: int = 0, accepted: int = 0):
    learner = MagicMock()
    report = MagicMock()
    report.proposals = [MagicMock() for _ in range(proposals)]
    report.accepted = accepted
    learner.distill.return_value = report
    return learner


class TestConfig(unittest.TestCase):
    def test_bad_interval_raises(self):
        with self.assertRaises(ValueError):
            al.LoopConfig(interval_s=0)

    def test_bad_iterations_raises(self):
        with self.assertRaises(ValueError):
            al.LoopConfig(max_iterations=-1)

    def test_bad_distill_every_raises(self):
        with self.assertRaises(ValueError):
            al.LoopConfig(distill_every=0)


class TestOneCycle(unittest.TestCase):
    def setUp(self):
        import os
        self._tmp = tempfile.TemporaryDirectory()
        self._seeds = Path(self._tmp.name) / "seeds.json"
        self._seeds.write_text(json.dumps([
            {
                "title": "Pet Bowl", "price": 30,
                "cost": 10, "daily_sales": 20,
                "saturation_score": 0.3,
            },
        ]))
        self._log = Path(self._tmp.name) / "loop.log"
        # AutopilotRequest requires shop_url; stub via env for tests
        self._prior = os.environ.get(
            "SHOPAI_SHOPIFY_URL",
        )
        os.environ["SHOPAI_SHOPIFY_URL"] = "test.myshopify.com"

    def tearDown(self):
        import os
        if self._prior is None:
            os.environ.pop(
                "SHOPAI_SHOPIFY_URL", None,
            )
        else:
            os.environ[
                "SHOPAI_SHOPIFY_URL"
            ] = self._prior
        self._tmp.cleanup()

    def _config(self, **overrides):
        base = dict(
            seeds_path=str(self._seeds),
            max_iterations=1,
            interval_s=0.01,
            log_path=str(self._log),
        )
        base.update(overrides)
        return al.LoopConfig(**base)

    def test_cycle_produces_summary(self):
        loop = al.AutopilotLoop(
            self._config(),
            autopilot=_make_autopilot(
                launches=2, successful=2,
            ),
            launch_learner=_make_learner(),
        )
        summaries = loop.run()
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s.launches, 2)
        self.assertEqual(s.successful, 2)
        self.assertEqual(s.mode, "dry_run")

    def test_log_file_written(self):
        loop = al.AutopilotLoop(
            self._config(),
            autopilot=_make_autopilot(),
            launch_learner=_make_learner(),
        )
        loop.run()
        lines = self._log.read_text().strip().split("\n")
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertIn("launches", entry)

    def test_live_mode_reflected(self):
        loop = al.AutopilotLoop(
            self._config(live=True),
            autopilot=_make_autopilot(),
            launch_learner=_make_learner(),
        )
        summaries = loop.run()
        self.assertEqual(summaries[0].mode, "live")

    def test_no_sources_records_error(self):
        # seeds file missing
        (self._tmp.name + "/nope.json")
        loop = al.AutopilotLoop(
            self._config(
                seeds_path="/nonexistent/seeds.json",
                peers="",
            ),
            autopilot=_make_autopilot(),
            launch_learner=_make_learner(),
        )
        summaries = loop.run()
        self.assertIn(
            "no winner sources", summaries[0].error,
        )

    def test_autopilot_exception_recorded(self):
        loop = al.AutopilotLoop(
            self._config(),
            autopilot=_make_autopilot(raise_exc=True),
            launch_learner=_make_learner(),
        )
        summaries = loop.run()
        self.assertIn(
            "autopilot raised", summaries[0].error,
        )
        self.assertEqual(summaries[0].launches, 0)


class TestIterations(unittest.TestCase):
    def setUp(self):
        import os
        self._tmp = tempfile.TemporaryDirectory()
        self._seeds = Path(self._tmp.name) / "seeds.json"
        self._seeds.write_text(json.dumps([
            {"title": "P", "price": 30, "cost": 10},
        ]))
        self._prior = os.environ.get(
            "SHOPAI_SHOPIFY_URL",
        )
        os.environ["SHOPAI_SHOPIFY_URL"] = "test.myshopify.com"

    def tearDown(self):
        import os
        if self._prior is None:
            os.environ.pop(
                "SHOPAI_SHOPIFY_URL", None,
            )
        else:
            os.environ[
                "SHOPAI_SHOPIFY_URL"
            ] = self._prior
        self._tmp.cleanup()

    def test_max_iterations_honored(self):
        loop = al.AutopilotLoop(
            al.LoopConfig(
                seeds_path=str(self._seeds),
                max_iterations=3,
                interval_s=0.01,
                log_path=str(
                    Path(self._tmp.name) / "loop.log",
                ),
            ),
            autopilot=_make_autopilot(),
            launch_learner=_make_learner(),
        )
        summaries = loop.run()
        self.assertEqual(len(summaries), 3)

    def test_distill_frequency(self):
        learner = _make_learner(
            proposals=2, accepted=1,
        )
        loop = al.AutopilotLoop(
            al.LoopConfig(
                seeds_path=str(self._seeds),
                max_iterations=6,
                interval_s=0.01,
                distill_every=3,
                log_path=str(
                    Path(self._tmp.name) / "loop.log",
                ),
            ),
            autopilot=_make_autopilot(),
            launch_learner=learner,
        )
        summaries = loop.run()
        # Distill called on cycles 3 and 6 → 2 calls
        self.assertEqual(learner.distill.call_count, 2)
        # Cycles 3 and 6 reflect the distill proposals
        self.assertEqual(
            summaries[2].distilled_proposals, 2,
        )
        self.assertEqual(
            summaries[5].distilled_proposals, 2,
        )
        # Cycles 1, 2, 4, 5 don't distill
        for idx in (0, 1, 3, 4):
            self.assertEqual(
                summaries[idx].distilled_proposals, 0,
            )


class TestStop(unittest.TestCase):
    def test_stop_during_run(self):
        import os
        prior = os.environ.get("SHOPAI_SHOPIFY_URL")
        os.environ["SHOPAI_SHOPIFY_URL"] = "test.myshopify.com"
        tmp = tempfile.TemporaryDirectory()
        try:
            seeds = Path(tmp.name) / "seeds.json"
            seeds.write_text(
                json.dumps([{"title": "P", "price": 30}]),
            )
            log = Path(tmp.name) / "loop.log"
            loop = al.AutopilotLoop(
                al.LoopConfig(
                    seeds_path=str(seeds),
                    max_iterations=100,
                    interval_s=0.5,
                    log_path=str(log),
                ),
                autopilot=_make_autopilot(),
                launch_learner=_make_learner(),
            )
            # Start in a thread, stop after a brief wait
            result_holder: dict = {}

            def _go():
                result_holder["summaries"] = loop.run()

            t = threading.Thread(target=_go)
            t.start()
            time.sleep(0.05)
            loop.request_stop()
            t.join(timeout=3.0)
            self.assertFalse(t.is_alive())
            # At least 1 cycle ran before stop
            self.assertGreaterEqual(
                len(result_holder["summaries"]), 1,
            )
        finally:
            tmp.cleanup()
            if prior is None:
                os.environ.pop(
                    "SHOPAI_SHOPIFY_URL", None,
                )
            else:
                os.environ[
                    "SHOPAI_SHOPIFY_URL"
                ] = prior


class TestSummarySerialise(unittest.TestCase):
    def test_summary_dict(self):
        s = al.CycleSummary(
            cycle=1, ts=100.0, mode="dry_run",
            launches=2, successful=1,
            distilled_proposals=0, accepted=0,
            duration_s=1.5,
        )
        d = s.as_dict()
        self.assertEqual(d["cycle"], 1)
        self.assertEqual(d["mode"], "dry_run")


if __name__ == "__main__":
    unittest.main()
