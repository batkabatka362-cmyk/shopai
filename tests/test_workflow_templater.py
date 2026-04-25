"""Workflow templater tests."""
from __future__ import annotations

import unittest

from core.brain import workflow_templater as wt


def _noop(ctx, inputs):
    return "ok"


class TestRegistry(unittest.TestCase):
    def test_register_and_get(self) -> None:
        r = wt.TemplateRegistry()
        r.register("x", lambda fn: None, required_params=("fn",))
        self.assertIsNotNone(r.get("x"))

    def test_duplicate_rejected(self) -> None:
        r = wt.TemplateRegistry()
        r.register("x", lambda: None)
        with self.assertRaises(ValueError):
            r.register("x", lambda: None)

    def test_blank_rejected(self) -> None:
        r = wt.TemplateRegistry()
        with self.assertRaises(ValueError):
            r.register("", lambda: None)

    def test_unregister(self) -> None:
        r = wt.TemplateRegistry()
        r.register("x", lambda: None)
        self.assertTrue(r.unregister("x"))
        self.assertFalse(r.unregister("x"))

    def test_list_sorted(self) -> None:
        r = wt.TemplateRegistry()
        r.register("b", lambda: None)
        r.register("a", lambda: None)
        names = [t.name for t in r.list_templates()]
        self.assertEqual(names, ["a", "b"])


class TestInstantiate(unittest.TestCase):
    def test_unknown_raises(self) -> None:
        r = wt.TemplateRegistry()
        with self.assertRaises(KeyError):
            r.instantiate("nope")

    def test_missing_params_raises(self) -> None:
        r = wt.default_registry()
        with self.assertRaises(ValueError) as cm:
            r.instantiate("daily_kill_sweep")
        self.assertIn("missing", str(cm.exception))


class TestDailyKillSweep(unittest.TestCase):
    def test_topology_4_stages(self) -> None:
        dag = wt.registry().instantiate(
            "daily_kill_sweep",
            fetch_metrics=_noop, decide_kill=_noop,
            execute_kill=_noop, notify=_noop,
        )
        viz = dag.visualise()
        self.assertIn("fetch_metrics", viz)
        self.assertIn("notify", viz)

    def test_executes_end_to_end(self) -> None:
        calls: list[str] = []

        def mk(tag):
            def fn(ctx, inputs):
                calls.append(tag)
                return tag
            return fn

        dag = wt.registry().instantiate(
            "daily_kill_sweep",
            fetch_metrics=mk("fetch"),
            decide_kill=mk("decide"),
            execute_kill=mk("execute"),
            notify=mk("notify"),
        )
        report = dag.execute()
        self.assertEqual(report.status, "ok")
        self.assertEqual(
            calls, ["fetch", "decide", "execute", "notify"],
        )

    def test_kill_failure_aborts(self) -> None:
        def boom(ctx, inputs):
            raise RuntimeError("shopify down")

        dag = wt.registry().instantiate(
            "daily_kill_sweep",
            fetch_metrics=_noop, decide_kill=_noop,
            execute_kill=boom, notify=_noop,
        )
        report = dag.execute()
        self.assertEqual(report.status, "aborted")


class TestWeeklyDigest(unittest.TestCase):
    def test_both_collectors_feed_format(self) -> None:
        outputs: dict[str, list] = {"inputs": []}

        def fmt(ctx, inputs):
            outputs["inputs"] = sorted(inputs.keys())
            return "report"

        dag = wt.registry().instantiate(
            "weekly_digest",
            collect_kpis=lambda c, i: {"rev": 100},
            collect_events=lambda c, i: {"n": 5},
            format_report=fmt,
            send=_noop,
        )
        report = dag.execute()
        self.assertEqual(report.status, "ok")
        self.assertEqual(
            outputs["inputs"], ["collect_events", "collect_kpis"],
        )


class TestProductLaunch(unittest.TestCase):
    def test_without_notify_still_works(self) -> None:
        dag = wt.registry().instantiate(
            "new_product_launch",
            ingest=_noop, enrich=_noop,
            publish=_noop, ads_launch=_noop,
        )
        self.assertNotIn("notify", dag.tasks())
        report = dag.execute()
        self.assertEqual(report.status, "ok")

    def test_with_notify_included(self) -> None:
        dag = wt.registry().instantiate(
            "new_product_launch",
            ingest=_noop, enrich=_noop,
            publish=_noop, ads_launch=_noop,
            notify=_noop,
        )
        self.assertIn("notify", dag.tasks())

    def test_publish_failure_aborts(self) -> None:
        def boom(ctx, inputs):
            raise RuntimeError("shopify rejected")
        dag = wt.registry().instantiate(
            "new_product_launch",
            ingest=_noop, enrich=_noop,
            publish=boom, ads_launch=_noop,
        )
        report = dag.execute()
        self.assertEqual(report.status, "aborted")


class TestAnomalyMonitor(unittest.TestCase):
    def test_alert_optional_doesnt_abort(self) -> None:
        def boom(ctx, inputs):
            raise RuntimeError("slack down")
        dag = wt.registry().instantiate(
            "anomaly_monitor",
            scan=_noop, triage=_noop, alert=boom,
        )
        report = dag.execute()
        # alert optional → partial status, not aborted
        self.assertIn(report.status, ("ok", "partial"))


class TestRetentionCycle(unittest.TestCase):
    def test_measure_optional(self) -> None:
        dag_no = wt.registry().instantiate(
            "retention_cycle",
            segment=_noop, predict_churn=_noop, act=_noop,
        )
        self.assertNotIn("measure", dag_no.tasks())

        dag_yes = wt.registry().instantiate(
            "retention_cycle",
            segment=_noop, predict_churn=_noop, act=_noop,
            measure=_noop,
        )
        self.assertIn("measure", dag_yes.tasks())


class TestDefaultRegistry(unittest.TestCase):
    def test_all_standard_templates_present(self) -> None:
        r = wt.default_registry()
        names = [t.name for t in r.list_templates()]
        for expected in (
            "daily_kill_sweep", "weekly_digest",
            "new_product_launch", "anomaly_monitor",
            "retention_cycle",
        ):
            self.assertIn(expected, names)

    def test_descriptions_non_empty(self) -> None:
        r = wt.default_registry()
        for tpl in r.list_templates():
            self.assertTrue(tpl.description)

    def test_global_singleton(self) -> None:
        wt.reset_registry()
        r1 = wt.registry()
        r2 = wt.registry()
        self.assertIs(r1, r2)


class TestCustomTemplate(unittest.TestCase):
    def test_user_template_works(self) -> None:
        r = wt.TemplateRegistry()

        def build(a, b):
            from core.system.workflow_dag import WorkflowDAG
            dag = WorkflowDAG()
            dag.add("a", a)
            dag.add("b", b, deps=("a",))
            return dag

        r.register(
            "two_step", build,
            required_params=("a", "b"),
            description="tiny",
        )
        dag = r.instantiate("two_step", a=_noop, b=_noop)
        self.assertEqual(dag.tasks(), ["a", "b"])


class TestDict(unittest.TestCase):
    def test_template_as_dict(self) -> None:
        tpl = wt.default_registry().get("daily_kill_sweep")
        d = tpl.as_dict()
        self.assertEqual(d["name"], "daily_kill_sweep")
        self.assertIn("fetch_metrics", d["required_params"])
        self.assertTrue(d["description"])


if __name__ == "__main__":
    unittest.main()
