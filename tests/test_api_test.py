"""Tests for engines.api_test -- W963-112."""
from __future__ import annotations

from unittest.mock import patch

from engines.api_test import ApiTestEngine
from engines.api_test.health_check import (
    ApiTestReport,
    HealthCheckResult,
    PROBES,
    run_api_test,
)


# ── HealthCheckResult cls property ────────────────────────


class TestHealthCheckResult:
    def test_cls_skipped_when_not_configured(self):
        r = HealthCheckResult(adapter="x", configured=False)
        assert r.cls == "skipped"

    def test_cls_ok_when_authenticated(self):
        r = HealthCheckResult(
            adapter="x",
            configured=True,
            reachable=True,
            authenticated=True,
        )
        assert r.cls == "ok"

    def test_cls_fail_when_configured_but_not_auth(self):
        """Pre-fix bug: configured + reachable + auth-fail
        was indistinguishable from skipped in some
        renderers because cls is a @property and asdict()
        omits it."""
        r = HealthCheckResult(
            adapter="x",
            configured=True,
            reachable=True,
            authenticated=False,
            error="HTTP 401",
        )
        assert r.cls == "fail"

    def test_cls_fail_when_configured_but_unreachable(self):
        r = HealthCheckResult(
            adapter="x",
            configured=True,
            reachable=False,
            authenticated=False,
            error="network down",
        )
        assert r.cls == "fail"


# ── run_api_test aggregator ───────────────────────────────


class TestRunApiTest:
    def test_no_configured_returns_empty_headline(self):
        """When no adapters have keys set, the aggregator
        reports headline + next_action guidance."""
        from engines.api_test import health_check as hc

        def fake_probe():
            return HealthCheckResult(
                adapter="x", configured=False,
            )

        # Replace PROBES entirely with a single skip probe
        with patch.object(
            hc, "PROBES", [("x", fake_probe)],
        ):
            report = run_api_test()
        assert report.configured_count == 0
        assert report.ok_count == 0
        assert "No adapters configured" in report.headline
        assert "api-status" in report.next_action

    def test_only_alias_filters_probes(self):
        """--alias openai runs ONLY the openai probe."""
        from engines.api_test import health_check as hc

        called = {"x": False, "y": False}

        def make_probe(name):
            def probe():
                called[name] = True
                return HealthCheckResult(
                    adapter=name, configured=False,
                )
            return probe

        with patch.object(
            hc, "PROBES",
            [("x", make_probe("x")), ("y", make_probe("y"))],
        ):
            report = run_api_test(only_alias="x")

        assert called["x"] is True
        assert called["y"] is False
        assert len(report.results) == 1

    def test_all_passing_reports_ready(self):
        from engines.api_test import health_check as hc

        def fake_probe():
            return HealthCheckResult(
                adapter="x",
                configured=True,
                reachable=True,
                authenticated=True,
                latency_ms=120.0,
                detail="ok",
            )

        with patch.object(
            hc, "PROBES", [("x", fake_probe)],
        ):
            report = run_api_test()
        assert report.ok_count == 1
        assert report.fail_count == 0
        assert "live + authenticated" in report.headline
        assert "earn-readiness" in report.next_action

    def test_one_failing_surfaces_first_fix(self):
        """When a probe fails, next_action guides operator
        to fix THAT adapter, not generic advice."""
        from engines.api_test import health_check as hc

        def fake_probe_a():
            return HealthCheckResult(
                adapter="brevo",
                configured=True,
                reachable=True,
                authenticated=False,
                error="HTTP 401 unauthorized IP",
            )

        def fake_probe_b():
            return HealthCheckResult(
                adapter="openai",
                configured=True,
                reachable=True,
                authenticated=True,
                detail="ok",
            )

        with patch.object(
            hc, "PROBES",
            [("brevo", fake_probe_a),
             ("openai", fake_probe_b)],
        ):
            report = run_api_test()
        assert report.fail_count == 1
        assert "brevo" in report.headline.lower()
        assert "brevo" in report.next_action.lower()

    def test_probe_crash_does_not_break_aggregator(self):
        """When an individual probe raises an exception
        OUTSIDE its own try/except, the aggregator still
        completes + flags that probe as failed."""
        from engines.api_test import health_check as hc

        def crashing_probe():
            raise RuntimeError("test: probe crashed")

        def ok_probe():
            return HealthCheckResult(
                adapter="ok",
                configured=True,
                reachable=True,
                authenticated=True,
            )

        with patch.object(
            hc, "PROBES",
            [("crash", crashing_probe),
             ("ok", ok_probe)],
        ):
            report = run_api_test()
        # Both probes ran; aggregator didn't propagate
        assert len(report.results) == 2
        crash_result = next(
            r for r in report.results
            if r.adapter == "crash"
        )
        assert "probe crashed" in crash_result.error
        assert report.ok_count == 1


# ── Probe registry sanity ─────────────────────────────────


class TestProbeRegistry:
    def test_every_probe_has_name_and_callable(self):
        for name, probe in PROBES:
            assert isinstance(name, str) and name
            assert callable(probe)

    def test_probe_names_unique(self):
        names = [name for name, _ in PROBES]
        assert len(names) == len(set(names))

    def test_required_probes_present(self):
        """Tier-1 adapters (the ones operator most often
        configures first) must be in PROBES."""
        names = {name for name, _ in PROBES}
        for required in (
            "shopify", "openai", "brevo",
            "pexels", "elevenlabs",
        ):
            assert required in names, (
                f"PROBES missing tier-1 adapter: {required}"
            )


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        # Each probe runs unconfigured (no .env). All
        # results land as skipped. Envelope still success.
        r = ApiTestEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert "error" in r

    def test_none_success(self):
        r = ApiTestEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = ApiTestEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = ApiTestEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = ApiTestEngine().run({})
        assert r["meta"]["engine"] == "api_test"

    def test_data_has_results(self):
        r = ApiTestEngine().run({})
        assert "results" in r["data"]
        assert isinstance(r["data"]["results"], list)

    def test_data_has_headline(self):
        r = ApiTestEngine().run({})
        assert r["data"]["headline"]
        assert r["data"]["next_action"]

    def test_results_carry_cls_field(self):
        """W963-112 BUG fix: cls is a @property which
        asdict() omits. flow.py must splice it in or the
        renderer can't tell skipped from fail."""
        r = ApiTestEngine().run({})
        for result in r["data"]["results"]:
            assert "cls" in result
            assert result["cls"] in (
                "ok", "fail", "skipped",
            )
