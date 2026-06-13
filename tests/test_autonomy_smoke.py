"""Tests for core.automation.autonomy_smoke (Wave 289-292)."""
from __future__ import annotations

from core.automation.autonomy_smoke import (
    SmokeDomainResult,
    SmokeReport,
    SmokeStep,
    _APPLY_NAMES,
    _APPLY_EMPTY_PAYLOAD,
    _DOMAINS,
    _LOG_MODULE_NAMES,
    _STATUS_MODULE_NAMES,
    _ANALYZE_NAMES,
    _safe_call,
    run_autonomy_smoke,
)


class TestCatalogs:

    def test_10_domains(self):
        assert len(_DOMAINS) == 10
        names = {d[0] for d in _DOMAINS}
        assert names == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
            "catalog_quality",
            "shipping_alert",
        }

    def test_apply_names_complete(self):
        for _, _, prefix, _ in _DOMAINS:
            assert prefix in _APPLY_NAMES, prefix
            assert prefix in _APPLY_EMPTY_PAYLOAD, prefix

    def test_log_module_names_complete(self):
        for _, _, prefix, _ in _DOMAINS:
            assert prefix in _LOG_MODULE_NAMES, prefix

    def test_status_module_names_complete(self):
        for _, _, prefix, _ in _DOMAINS:
            assert prefix in _STATUS_MODULE_NAMES, prefix

    def test_analyze_names_complete(self):
        for _, _, prefix, _ in _DOMAINS:
            assert prefix in _ANALYZE_NAMES, prefix

    def test_refund_takes_two_positional(self):
        # apply_refunds(processed, fraud_flags) requires both
        assert _APPLY_EMPTY_PAYLOAD["refund"] == ([], [])

    def test_others_take_one_positional(self):
        for prefix, args in _APPLY_EMPTY_PAYLOAD.items():
            if prefix == "refund":
                continue
            assert args == ([],), prefix


class TestSafeCall:

    def test_success(self):
        ok, detail, result = _safe_call(lambda: 42)
        assert ok
        assert result == 42

    def test_raises(self):
        def boom():
            raise ValueError("nope")
        ok, detail, result = _safe_call(boom)
        assert not ok
        assert "nope" in detail
        assert result is None

    def test_with_args(self):
        ok, _, result = _safe_call(lambda x, y: x + y, 2, 3)
        assert ok
        assert result == 5


class TestRunAutonomySmoke:

    def test_returns_report(self):
        r = run_autonomy_smoke()
        assert isinstance(r, SmokeReport)

    def test_covers_10_domains(self):
        r = run_autonomy_smoke()
        assert len(r.domains) == 10

    def test_live_all_ok(self):
        r = run_autonomy_smoke()
        assert r.overall_cls == "ok", [
            (d.domain, [s for s in d.steps if not s.ok])
            for d in r.domains if d.cls == "error"
        ]
        assert r.ok_count == 10
        assert r.error_count == 0

    def test_each_domain_has_5_steps(self):
        r = run_autonomy_smoke()
        for d in r.domains:
            assert len(d.steps) == 5, (d.domain, d.steps)


class TestSmokeReportCounts:

    def test_mixed_counts(self):
        r = SmokeReport()
        r.domains = [
            SmokeDomainResult(domain="a", cls="ok"),
            SmokeDomainResult(domain="b", cls="error"),
            SmokeDomainResult(domain="c", cls="ok"),
        ]
        assert r.ok_count == 2
        assert r.error_count == 1


class TestSmokeDomainResultErrorCount:

    def test_zero_errors(self):
        d = SmokeDomainResult(domain="x")
        d.steps = [
            SmokeStep(name="a", ok=True),
            SmokeStep(name="b", ok=True),
        ]
        assert d.error_count == 0

    def test_some_errors(self):
        d = SmokeDomainResult(domain="x")
        d.steps = [
            SmokeStep(name="a", ok=True),
            SmokeStep(name="b", ok=False, detail="boom"),
            SmokeStep(name="c", ok=False, detail="boom"),
        ]
        assert d.error_count == 2
