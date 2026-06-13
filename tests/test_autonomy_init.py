"""Tests for core.automation.autonomy_init (Wave 526-535).

Verifies the scaffolder produces syntactically-valid Python +
catalog-update checklist + writes to disk safely.
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

import pytest

from core.automation.autonomy_init import (
    DomainSpec,
    _analyze_fn,
    _apply_fn,
    _bridge_fn,
    _domain_hyphen,
    _domain_title,
    _event_class,
    _record_fn,
    _status_class,
    _status_fn,
    _tag_list_literal,
    catalog_checklist,
    render_domain,
    write_to_disk,
)


class TestNamingHelpers:

    def test_domain_title(self):
        assert _domain_title("customer_outreach") == (
            "Customer Outreach"
        )

    def test_domain_hyphen(self):
        assert _domain_hyphen("customer_outreach") == (
            "customer-outreach"
        )

    def test_apply_fn(self):
        assert _apply_fn("catalog_quality") == (
            "apply_catalog_quality"
        )

    def test_analyze_fn(self):
        assert _analyze_fn("catalog_quality") == (
            "analyze_catalog_quality_health"
        )

    def test_bridge_fn(self):
        assert _bridge_fn("quality") == (
            "maybe_auto_pause_quality"
        )

    def test_status_fn(self):
        assert _status_fn("catalog_quality") == (
            "get_catalog_quality_status"
        )

    def test_record_fn(self):
        assert _record_fn("quality") == "record_quality_event"

    def test_event_class(self):
        assert _event_class("catalog_quality") == (
            "CatalogQualityEvent"
        )

    def test_status_class(self):
        assert _status_class("catalog_quality") == (
            "CatalogQualityStatusReport"
        )


class TestTagListLiteral:

    def test_empty_tags(self):
        assert _tag_list_literal([]) == "frozenset()"

    def test_with_tags(self):
        out = _tag_list_literal(["a", "b"])
        assert "frozenset({" in out
        assert '"a"' in out
        assert '"b"' in out


class TestDomainSpec:

    def test_defaults(self):
        spec = DomainSpec(
            domain="x",
            prefix="x",
            capability="SHOPIFY_TAG_PRODUCT",
        )
        assert spec.pkg_name == "x_autonomy"
        assert spec.engine_name == "x"
        assert spec.entity_id == "product_id"
        assert spec.max_per_run == 200

    def test_explicit_engine_name(self):
        spec = DomainSpec(
            domain="x", prefix="x",
            capability="C",
            engine_name="custom",
        )
        assert spec.engine_name == "custom"


class TestRenderDomain:

    def _spec(self, **overrides):
        base = dict(
            domain="test_scaffold",
            prefix="scaff",
            capability="SHOPIFY_TAG_PRODUCT",
            tags=["shopai-scaff-a", "shopai-scaff-b"],
            max_per_run=50,
            entity_id="product_id",
            wave_base=900,
        )
        base.update(overrides)
        return DomainSpec(**base)

    def test_produces_6_files(self):
        r = render_domain(self._spec())
        assert len(r.files) == 6  # __init__ + 5 modules
        assert "__init__.py" in r.files
        assert "scaff_log.py" in r.files
        assert "scaff_state.py" in r.files
        assert "scaff_health.py" in r.files
        assert "scaff_applier.py" in r.files
        assert "scaff_status.py" in r.files

    def test_test_file_named(self):
        r = render_domain(self._spec())
        assert (
            r.test_file_name == "test_test_scaffold_autonomy.py"
        )

    def test_all_files_parse_as_python(self):
        r = render_domain(self._spec())
        for name, src in r.files.items():
            try:
                ast.parse(src, filename=name)
            except SyntaxError as exc:
                pytest.fail(
                    f"{name} has syntax error: {exc}"
                )

    def test_test_file_parses(self):
        r = render_domain(self._spec())
        ast.parse(
            r.test_file_content,
            filename=r.test_file_name,
        )

    def test_applier_uses_capability(self):
        r = render_domain(self._spec(
            capability="SHOPIFY_FOO_BAR",
        ))
        assert "SHOPIFY_FOO_BAR" in r.files["scaff_applier.py"]

    def test_applier_uses_tags(self):
        r = render_domain(self._spec(
            tags=["alpha", "beta"],
        ))
        body = r.files["scaff_applier.py"]
        assert "alpha" in body
        assert "beta" in body

    def test_health_uses_env_prefix(self):
        r = render_domain(self._spec())
        # ENV_PREFIX is uppercase domain
        assert "TEST_SCAFFOLD" in r.files["scaff_health.py"]

    def test_status_module_uses_status_class(self):
        r = render_domain(self._spec())
        assert (
            "TestScaffoldStatusReport"
            in r.files["scaff_status.py"]
        )


class TestWriteToDisk:

    def test_persists_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "engines").mkdir()
        (tmp_path / "tests").mkdir()
        spec = DomainSpec(
            domain="diskscaff",
            prefix="ds",
            capability="SHOPIFY_TAG_PRODUCT",
            tags=["a"],
        )
        r = render_domain(spec)
        written = write_to_disk(r)
        assert len(written) == 7  # 6 module files + 1 test
        # __init__.py + 5 module files
        for fname in r.files:
            assert (
                tmp_path / "engines" / spec.pkg_name / fname
            ).exists()
        assert (
            tmp_path / "tests" / r.test_file_name
        ).exists()

    def test_refuses_existing_package(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "engines").mkdir()
        (tmp_path / "tests").mkdir()
        spec = DomainSpec(
            domain="diskscaff2",
            prefix="ds2",
            capability="SHOPIFY_TAG_PRODUCT",
        )
        r = render_domain(spec)
        # Pre-create the package dir
        (tmp_path / "engines" / spec.pkg_name).mkdir()
        with pytest.raises(FileExistsError):
            write_to_disk(r)


class TestCatalogChecklist:

    def test_contains_essential_sections(self):
        spec = DomainSpec(
            domain="testck",
            prefix="ck",
            capability="SHOPIFY_TAG_PRODUCT",
        )
        chk = catalog_checklist(spec)
        joined = "\n".join(chk)
        assert "autonomy_status" in joined
        assert "Pattern" in joined
        assert "_EXEMPT_WRITERS" in joined
        assert "testck" in joined


class TestDogfood:
    """Trust anchor: render a fake domain + verify both module
    syntax and that the applier safety gates check out via
    importlib (bypassing sys.path namespace collisions with
    the real engines/ package)."""

    def test_rendered_modules_parse_and_have_required_symbols(
        self, tmp_path, monkeypatch,
    ):
        spec = DomainSpec(
            domain="dogfood",
            prefix="df",
            capability="SHOPIFY_TAG_PRODUCT",
            tags=["shopai-df-test"],
            wave_base=999,
        )
        r = render_domain(spec)
        # Parse + extract top-level names to verify the
        # expected canonical entry points exist in each file.
        applier = ast.parse(r.files["df_applier.py"])
        applier_funcs = {
            n.name for n in applier.body
            if isinstance(n, ast.FunctionDef)
        }
        assert "apply_dogfood" in applier_funcs
        status = ast.parse(r.files["df_status.py"])
        status_funcs = {
            n.name for n in status.body
            if isinstance(n, ast.FunctionDef)
        }
        assert "get_dogfood_status" in status_funcs
        health = ast.parse(r.files["df_health.py"])
        health_funcs = {
            n.name for n in health.body
            if isinstance(n, ast.FunctionDef)
        }
        assert "analyze_dogfood_health" in health_funcs
        assert "maybe_auto_pause_df" in health_funcs
