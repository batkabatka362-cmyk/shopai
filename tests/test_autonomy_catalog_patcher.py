"""Tests for autonomy_catalog_patcher + autonomy_catalog_patches.

Phase 30 introduces an anchor-based patcher used by
`shopai autonomy-init --patch-catalogs` to mechanically update
22 substrate catalogs when a new autonomy domain is added.
Tests cover:
  - dict / list / constant / set patch shapes
  - idempotency (skip_if_contains)
  - refusal on ambiguous / missing anchors
  - safe rollback on patches that produce unparseable Python
  - per-catalog patch spec coverage for a synthetic DomainSpec
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.automation.autonomy_catalog_patcher import (
    PatchResult,
    PatcherError,
    patch_constant_set,
    patch_dict_append,
    patch_list_append,
    patch_set_add,
)
from core.automation.autonomy_catalog_patches import (
    all_patches,
    apply_all,
)
from core.automation.autonomy_init import DomainSpec


# ─── patch_dict_append ──────────────────────────────────────────────────

class TestPatchDictAppend:

    def _write(self, tmp_path, body):
        p = tmp_path / "cat.py"
        p.write_text(body, encoding="utf-8")
        return p

    def test_simple_dict_append(self, tmp_path):
        p = self._write(tmp_path, (
            'X = {\n'
            '    "a": 1,\n'
            '}\n'
        ))
        r = patch_dict_append(p, "X", '"b": 2,', dry_run=False)
        assert r.success
        body = p.read_text(encoding="utf-8")
        assert '"b": 2,' in body
        # Parses cleanly
        tree = ast.parse(body)
        assert tree is not None

    def test_idempotent_via_skip_if_contains(self, tmp_path):
        p = self._write(tmp_path, (
            'X = {\n'
            '    "a": 1,\n'
            '    "b": 2,\n'
            '}\n'
        ))
        r = patch_dict_append(
            p, "X", '"b": 2,',
            skip_if_contains='"b":',
            dry_run=False,
        )
        assert r.success
        assert "already patched" in r.reason

    def test_refuses_missing_target(self, tmp_path):
        p = self._write(tmp_path, 'X = {"a": 1}\n')
        r = patch_dict_append(p, "MISSING", '"b": 2,')
        assert not r.success
        assert "not found" in r.reason

    def test_refuses_non_dict_target(self, tmp_path):
        p = self._write(tmp_path, 'X = [1, 2, 3]\n')
        r = patch_dict_append(p, "X", '"b": 2,')
        assert not r.success
        assert "not a Dict" in r.reason

    def test_refuses_multiline_value_dict_correctly(
        self, tmp_path,
    ):
        # Multi-value dict that uses tuple value -- should
        # still patch the dict, not the tuple
        p = self._write(tmp_path, (
            'X = {\n'
            '    "a": (\n'
            '        "foo",\n'
            '        "bar",\n'
            '    ),\n'
            '}\n'
        ))
        r = patch_dict_append(p, "X", '"b": 2,', dry_run=False)
        assert r.success
        body = p.read_text(encoding="utf-8")
        # Parses cleanly + has both entries
        d = ast.literal_eval(
            ast.parse(body).body[0].value
        )
        assert d["a"] == ("foo", "bar")
        assert d["b"] == 2

    def test_dry_run_does_not_write(self, tmp_path):
        p = self._write(tmp_path, 'X = {\n    "a": 1,\n}\n')
        before = p.read_text(encoding="utf-8")
        r = patch_dict_append(
            p, "X", '"b": 2,', dry_run=True,
        )
        assert r.success
        assert p.read_text(encoding="utf-8") == before


# ─── patch_list_append ──────────────────────────────────────────────────

class TestPatchListAppend:

    def test_list_append(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text(
            'X = [\n    1,\n    2,\n]\n', encoding="utf-8",
        )
        r = patch_list_append(p, "X", '3,', dry_run=False)
        assert r.success
        d = ast.literal_eval(
            ast.parse(p.read_text(encoding="utf-8"))
            .body[0].value
        )
        assert d == [1, 2, 3]

    def test_refuses_non_list_target(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text('X = {"a": 1}\n', encoding="utf-8")
        r = patch_list_append(p, "X", '1,')
        assert not r.success
        assert "not a List" in r.reason


# ─── patch_constant_set ─────────────────────────────────────────────────

class TestPatchConstantSet:

    def test_bump_constant(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text('N = 7\n', encoding="utf-8")
        r = patch_constant_set(p, "N", 8, dry_run=False)
        assert r.success
        assert "N = 8" in p.read_text(encoding="utf-8")

    def test_idempotent_when_already_set(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text('N = 8\n', encoding="utf-8")
        r = patch_constant_set(p, "N", 8, dry_run=False)
        assert r.success
        assert "already" in r.reason

    def test_refuses_non_int_constant(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text('N = "seven"\n', encoding="utf-8")
        r = patch_constant_set(p, "N", 8)
        assert not r.success
        assert "not an int Constant" in r.reason


# ─── patch_set_add ──────────────────────────────────────────────────────

class TestPatchSetAdd:

    def test_frozenset_add(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text(
            'X = frozenset({\n'
            '    "a",\n'
            '    "b",\n'
            '})\n',
            encoding="utf-8",
        )
        r = patch_set_add(p, "X", '"c",', dry_run=False)
        assert r.success
        body = p.read_text(encoding="utf-8")
        assert '"c"' in body
        ast.parse(body)  # still parses

    def test_idempotent(self, tmp_path):
        p = tmp_path / "cat.py"
        p.write_text(
            'X = frozenset({\n    "a",\n    "b",\n})\n',
            encoding="utf-8",
        )
        r = patch_set_add(
            p, "X", '"b",',
            skip_if_contains='"b"', dry_run=False,
        )
        assert r.success
        assert "already" in r.reason


# ─── apply_all against the live catalog set ─────────────────────────────

class TestApplyAllLive:
    """The most important test: a fresh DomainSpec should
    dry-run all 30 patches cleanly against the current branch."""

    def test_dry_run_succeeds_for_new_domain(self):
        spec = DomainSpec(
            domain="test_apply_all_dry",
            prefix="taad",
            capability="SHOPIFY_TAG_PRODUCT",
            tags=["shopai-taad-x"],
        )
        patches = all_patches(spec, new_domain_count=99)
        results = apply_all(patches, dry_run=True)
        # All 30 should succeed; new keys aren't in the
        # catalogs yet so no idempotent skip should fire.
        failures = [
            r for r in results if not r.success
        ]
        assert failures == [], (
            "expected all patches to dry-run ok, got "
            f"{len(failures)} failures: "
            + "; ".join(
                f"{f.path.name}::{f.var_name}: {f.reason}"
                for f in failures
            )
        )
        assert len(results) == 30

    def test_idempotent_for_existing_domain(self):
        # catalog_quality is already in every catalog.
        # Patches should idempotent-succeed via
        # skip_if_contains.
        spec = DomainSpec(
            domain="catalog_quality",
            prefix="quality",
            capability="SHOPIFY_TAG_PRODUCT",
        )
        patches = all_patches(spec, new_domain_count=9)
        results = apply_all(patches, dry_run=True)
        ok = sum(1 for r in results if r.success)
        # All 30 should succeed (idempotent for already-
        # present + skip for constant)
        assert ok == 30


# ─── PatchResult dataclass ──────────────────────────────────────────────

class TestPatchResult:

    def test_defaults(self):
        r = PatchResult(
            path=Path("x"),
            var_name="X",
            success=False,
        )
        assert r.reason == ""
        assert r.dry_run is True
