"""Tests for engines.api_test -- W963-112 + W963-113."""
from __future__ import annotations

from unittest.mock import patch

from engines.api_test import ApiTestEngine
from engines.api_test.health_check import (
    ApiTestReport,
    HealthCheckResult,
    PROBES,
    _extract_error_message,
    _short_http_error,
    run_api_test,
)


# ── W963-113 error parsing ────────────────────────────────


class TestExtractErrorMessage:
    """Vendor error bodies come in JSON-nested shapes that
    bury the operator-actionable message. The extractor
    pulls it out + falls back gracefully when the JSON is
    truncated by upstream snippeting."""

    def test_openai_nested_shape(self):
        body = (
            '{"error": {"message": "Invalid API key", '
            '"type": "auth_error"}}'
        )
        assert (
            _extract_error_message(body) == "Invalid API key"
        )

    def test_brevo_flat_shape(self):
        body = (
            '{"code": "unauthorized", '
            '"message": "Bad key"}'
        )
        assert _extract_error_message(body) == "Bad key"

    def test_klaviyo_errors_list(self):
        body = (
            '{"errors": [{"detail": "Invalid token", '
            '"title": "Auth failed"}]}'
        )
        assert (
            _extract_error_message(body) == "Invalid token"
        )

    def test_plain_text_returned_as_is(self):
        body = "Not authorised"
        assert _extract_error_message(body) == "Not authorised"

    def test_empty_returns_empty(self):
        assert _extract_error_message("") == ""

    def test_truncated_json_with_closed_message(self):
        """Upstream sometimes truncates the JSON body at
        char N, but if the message itself fit, the regex
        fallback should still find it."""
        body = (
            'openai: rate limit (429): {\n'
            '    "error": {\n'
            '        "message": "You exceeded your quota."\n'
            '        '
        )
        result = _extract_error_message(body)
        assert result == "You exceeded your quota."

    def test_truncated_json_with_truncated_message(self):
        """W963-113 BUG fix: when upstream snippeting cuts
        OFF the closing quote of "message": "...", the
        regex must still extract everything up to the
        truncation point. Pre-fix the regex required the
        closing quote so this path returned the full raw
        body unchanged."""
        body = (
            'openai: rate limit (429): {\n'
            '    "error": {\n'
            '        "message": "You exceeded your quota, '
            'please check your billing'
        )
        result = _extract_error_message(body)
        assert "You exceeded your quota" in result
        assert "please check your billing" in result
        # NOT the raw JSON body
        assert '"error"' not in result
        assert '"message"' not in result

    def test_meta_ads_nested_shape(self):
        body = (
            '{"error": {"message": "Invalid OAuth token", '
            '"code": 190, "type": "OAuthException"}}'
        )
        assert (
            _extract_error_message(body)
            == "Invalid OAuth token"
        )


class TestShortHttpError:
    def test_brevo_401_extracts_clean_message(self):
        body = (
            '{"message": "We have detected you are using '
            'an unrecognised IP address 1.2.3.4"}'
        )
        result = _short_http_error(401, body)
        assert "HTTP 401:" in result
        assert "unrecognised IP address" in result
        # JSON braces stripped
        assert '"{' not in result

    def test_plain_html_body_passes_through(self):
        result = _short_http_error(500, "<html>Server Error</html>")
        assert "HTTP 500" in result
        assert "Server Error" in result

    def test_empty_body(self):
        result = _short_http_error(503, "")
        assert "HTTP 503" in result


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
