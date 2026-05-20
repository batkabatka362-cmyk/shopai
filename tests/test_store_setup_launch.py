"""Tests for ``engines.store_setup.launch_orchestrator``.

End-to-end ``launch_store`` runs the per-capability generators
and appliers (policies, pages, welcome discount, collections,
brand assets, product descriptions, SEO meta) and returns a
unified checklist + rollup writeback.

Coverage:
  1. Empty store_name -> early-exit, not ready, no apply calls.
  2. Required steps succeed -> ready_to_launch=True even when
     all optional steps are skipped.
  3. Optional steps (discount, collections, brand,
     descriptions, seo) skip cleanly when disabled / inputs
     missing -- and do NOT block ready_to_launch.
  4. Each REQUIRED step (policies, pages) failing flips
     ready_to_launch to False.
  5. Each OPTIONAL step failing does NOT flip ready_to_launch.
  6. Rollup writeback fires with failed_steps + applied_<step>
     metrics + SHOPAI_LAUNCH_STORE capability.
  7. store_id propagates to each sub-call + the rollup params.
  8. Per-step exception isolation -- a raise in one step does
     not abort the orchestrator.
  9. Brand step runs only when a URL is supplied.
 10. Product enrichment steps run only when products supplied.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.store_setup.launch_orchestrator import launch_store


# ── Shared patch helper ────────────────────────────────────────


def _patch_required_steps(
    *,
    policies_applied: int = 1,
    pages_applied: int = 1,
    policies_error: str | None = None,
    pages_error: str | None = None,
    policies_raise: Exception | None = None,
    pages_raise: Exception | None = None,
):
    """Build the patch context for policies + pages (required).

    Returns a list of patch context managers; caller uses
    ``contextlib.ExitStack`` to enter them all.
    """
    patches = []

    if policies_raise:
        patches.append(patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            side_effect=policies_raise,
        ))
        patches.append(patch(
            "engines.store_setup.policy_applier.apply_policies",
        ))
    else:
        patches.append(patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ))
        patches.append(patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={
                "applied_count": policies_applied,
                "results": [],
                "error": policies_error,
            },
        ))

    if pages_raise:
        patches.append(patch(
            "engines.store_setup.page_generator.generate_pages",
            side_effect=pages_raise,
        ))
        patches.append(patch(
            "engines.store_setup.page_applier.apply_pages",
        ))
    else:
        patches.append(patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ))
        patches.append(patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={
                "applied_count": pages_applied,
                "results": [],
                "error": pages_error,
            },
        ))

    # Always silence the rollup writeback.
    patches.append(patch(
        "engines.store_setup.launch_orchestrator."
        "record_writeback",
    ))
    return patches


def _enter(stack, patches):
    return [stack.enter_context(p) for p in patches]


# ── 1. Empty name ─────────────────────────────────────────────


class TestEmptyName:

    def test_empty_string_returns_not_ready(self):
        with patch(
            "engines.store_setup.policy_applier.apply_policies",
        ) as p_apply, patch(
            "engines.store_setup.page_applier.apply_pages",
        ) as page_apply:
            result = launch_store(store_name="")
        assert result["ready_to_launch"] is False
        assert result["error"] == "store_name_required"
        p_apply.assert_not_called()
        page_apply.assert_not_called()

    def test_whitespace_only(self):
        result = launch_store(store_name="   ")
        assert result["ready_to_launch"] is False


# ── 2. Required-only happy path ───────────────────────────────


class TestRequiredOnlyHappyPath:
    """Required steps succeed, optional steps all skipped."""

    def test_ready_to_launch_with_only_required(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert result["ready_to_launch"] is True
        assert result["policies"]["applied_count"] == 1
        assert result["pages"]["applied_count"] == 1
        # Discount + collections were disabled
        assert result["discount"].get("skipped") is True
        assert result["collections"].get("skipped") is True
        # Brand + product enrichers skip because no inputs
        assert result["brand"].get("skipped") is True
        assert result["descriptions"].get("skipped") is True
        assert result["seo"].get("skipped") is True
        # Checklist has 7 steps total
        assert len(result["checklist"]) == 7

    def test_checklist_rows_have_full_shape(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        for row in result["checklist"]:
            assert "step" in row
            assert "ok" in row
            assert "applied" in row
            assert "error" in row
            assert "skipped" in row


# ── 3. Optional steps skipped cleanly ─────────────────────────


class TestOptionalSkips:

    def test_disabled_flags_record_skip_reason(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert (
            result["discount"]["skip_reason"] == "disabled"
        )
        assert (
            result["collections"]["skip_reason"] == "disabled"
        )

    def test_no_brand_urls_skip_reason(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert (
            result["brand"]["skip_reason"]
            == "no_brand_urls_provided"
        )

    def test_no_products_skip_reason(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert (
            result["descriptions"]["skip_reason"]
            == "no_products"
        )
        assert result["seo"]["skip_reason"] == "no_products"

    def test_skipped_steps_are_ok_in_checklist(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        skipped_rows = [
            r for r in result["checklist"] if r["skipped"]
        ]
        for row in skipped_rows:
            assert row["ok"] is True
            assert row["applied"] == 0


# ── 4. Required-step failure flips ready_to_launch ────────────


class TestRequiredFailure:

    def test_policies_zero_applies_blocks_readiness(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps(
                policies_applied=0,
                policies_error="rejected",
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert result["ready_to_launch"] is False
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["policies"]["ok"] is False
        assert steps["pages"]["ok"] is True

    def test_pages_zero_applies_blocks_readiness(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps(
                pages_applied=0,
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert result["ready_to_launch"] is False


# ── 5. Optional-step failure does NOT block readiness ─────────


class TestOptionalFailureDoesNotBlock:

    def test_collections_failure_does_not_block(self):
        """Collections fails (applied_count=0, error set) but
        readiness still True because collections is optional."""
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            # Override collections to FAIL
            stack.enter_context(patch(
                "engines.store_setup.collection_seeder."
                "generate_starter_collections",
                return_value=[{"title": "All"}],
            ))
            stack.enter_context(patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={
                    "applied_count": 0,
                    "results": [],
                    "error": "router_unavailable",
                },
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=True,
            )
        # Required steps both OK -> ready, even though
        # the optional collections step failed.
        assert result["ready_to_launch"] is True
        assert result["collections"]["applied_count"] == 0


# ── 6. Rollup writeback ───────────────────────────────────────


class TestRollupWriteback:

    def test_records_with_capability_and_metrics(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            patches = _patch_required_steps()
            # Remove the auto-silenced record_writeback patch
            # (last item) and replace with a captured mock.
            patches.pop()
            _enter(stack, patches)
            record_mock = stack.enter_context(patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ))
            launch_store(
                store_name="Acme",
                niche="beauty",
                region="us",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "store_setup"
        assert kwargs["action_type"] == "launch_store"
        assert kwargs["capability"] == "SHOPAI_LAUNCH_STORE"
        assert kwargs["success"] is True
        metrics = kwargs["metrics"]
        assert metrics["ready_to_launch"] is True
        # Per-step applied_<step> metrics for every checklist
        # entry.
        for step in (
            "policies", "pages", "discount", "collections",
            "brand", "descriptions", "seo",
        ):
            assert f"applied_{step}" in metrics
        assert metrics["applied_policies"] == 1
        assert metrics["applied_pages"] == 1
        # No failed steps when only-required happy path
        assert metrics["failed_steps"] == []

    def test_failed_steps_listed_in_metrics(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            patches = _patch_required_steps(
                policies_applied=0,
                policies_error="rejected",
            )
            patches.pop()
            _enter(stack, patches)
            record_mock = stack.enter_context(patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ))
            launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert "policies" in kwargs["metrics"]["failed_steps"]
        # Error string mentions the failing step + reason
        assert "policies" in (kwargs["error"] or "")


# ── 7. store_id propagation ───────────────────────────────────


class TestStoreIdPropagation:

    def test_store_id_threads_through(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ))
            policy_mock = stack.enter_context(patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={
                    "applied_count": 1, "results": [],
                },
            ))
            stack.enter_context(patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ))
            page_mock = stack.enter_context(patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={
                    "applied_count": 1, "results": [],
                },
            ))
            record_mock = stack.enter_context(patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ))
            launch_store(
                store_name="Acme",
                store_id="store-a",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert (
            policy_mock.call_args.kwargs["store_id"]
            == "store-a"
        )
        assert (
            page_mock.call_args.kwargs["store_id"]
            == "store-a"
        )
        assert (
            record_mock.call_args.kwargs["params"][
                "store_id"
            ] == "store-a"
        )

    def test_store_id_propagates_to_optional_steps(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            disc_mock = stack.enter_context(patch(
                "engines.store_setup.welcome_discount."
                "generate_welcome_discount",
                return_value={"code": "WELCOME10"},
            ))
            disc_apply = stack.enter_context(patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={"applied": True},
            ))
            launch_store(
                store_name="Acme",
                store_id="store-b",
                enable_welcome_discount=True,
                enable_collections=False,
            )
        # generator does NOT need store_id, but applier does
        assert (
            disc_apply.call_args.kwargs["store_id"]
            == "store-b"
        )
        # Discount generator just got store_name + niche, not
        # store_id -- verify it was called
        assert disc_mock.called


# ── 8. Per-step exception isolation ───────────────────────────


class TestExceptionIsolation:

    def test_policies_raise_does_not_block_pages(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps(
                policies_raise=RuntimeError("generator broken"),
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert (
            "generator broken"
            in (result["policies"]["error"] or "")
        )
        # Pages still ran
        assert result["pages"]["applied_count"] == 1
        assert result["ready_to_launch"] is False

    def test_pages_raise_does_not_block_policies(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps(
                pages_raise=RuntimeError("generator broken"),
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert result["policies"]["applied_count"] == 1
        assert (
            "generator broken"
            in (result["pages"]["error"] or "")
        )

    def test_optional_step_raise_isolates_to_that_step(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            stack.enter_context(patch(
                "engines.store_setup.welcome_discount."
                "generate_welcome_discount",
                side_effect=RuntimeError("disc broken"),
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=True,
                enable_collections=False,
            )
        # Required steps OK -> ready_to_launch True; optional
        # discount captured its error but didn't block.
        assert result["ready_to_launch"] is True
        assert "disc broken" in (
            result["discount"]["error"] or ""
        )


# ── 9. Brand step gating ──────────────────────────────────────


class TestBrandStep:

    def test_runs_when_any_url_supplied(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            brand_mock = stack.enter_context(patch(
                "engines.store_setup.brand_uploader."
                "upload_brand_assets",
                return_value={
                    "uploaded_count": 2,
                    "files": [
                        {"slot": "logo", "ok": True},
                        {"slot": "favicon", "ok": True},
                    ],
                },
            ))
            result = launch_store(
                store_name="Acme",
                logo_url="https://cdn/logo.png",
                favicon_url="https://cdn/fav.png",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        brand_mock.assert_called_once()
        assert result["brand"]["applied_count"] == 2
        assert result["brand"].get("skipped") is not True

    def test_skips_when_no_urls(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            brand_mock = stack.enter_context(patch(
                "engines.store_setup.brand_uploader."
                "upload_brand_assets",
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        brand_mock.assert_not_called()
        assert result["brand"]["skipped"] is True


# ── 10. Product enrichment gating ─────────────────────────────


class TestProductEnrichmentStep:

    def test_runs_when_products_supplied(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            desc_enrich = stack.enter_context(patch(
                "engines.store_setup."
                "product_description_enricher.enrich_products",
                return_value={
                    "generated": [
                        {"id": "gid://p/1",
                         "body_html": "<p>x</p>"},
                    ],
                },
            ))
            desc_apply = stack.enter_context(patch(
                "engines.store_setup."
                "product_description_enricher.apply_descriptions",
                return_value={
                    "applied_count": 1, "results": [],
                },
            ))
            seo_enrich = stack.enter_context(patch(
                "engines.store_setup.seo_meta_enricher."
                "enrich_seo",
                return_value={
                    "generated": [
                        {"id": "gid://p/1",
                         "seo_title": "t",
                         "seo_description": "d"},
                    ],
                },
            ))
            seo_apply = stack.enter_context(patch(
                "engines.store_setup.seo_meta_enricher."
                "apply_seo",
                return_value={
                    "applied_count": 1, "results": [],
                },
            ))
            result = launch_store(
                store_name="Acme",
                products=[{
                    "id": "gid://p/1",
                    "title": "Mascara",
                    "body_html": "",
                }],
                enable_welcome_discount=False,
                enable_collections=False,
            )
        desc_enrich.assert_called_once()
        desc_apply.assert_called_once()
        seo_enrich.assert_called_once()
        seo_apply.assert_called_once()
        assert result["descriptions"]["applied_count"] == 1
        assert result["seo"]["applied_count"] == 1

    def test_skips_when_no_products(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            _enter(stack, _patch_required_steps())
            d_enrich = stack.enter_context(patch(
                "engines.store_setup."
                "product_description_enricher.enrich_products",
            ))
            seo_enrich = stack.enter_context(patch(
                "engines.store_setup.seo_meta_enricher."
                "enrich_seo",
            ))
            result = launch_store(
                store_name="Acme",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        d_enrich.assert_not_called()
        seo_enrich.assert_not_called()
        assert result["descriptions"]["skipped"] is True
        assert result["seo"]["skipped"] is True


# ── 11. Forwarded optional flags ──────────────────────────────


class TestOptionalFlags:

    def test_legal_notice_and_subscription_flags_forward(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            gen_mock = stack.enter_context(patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={},
            ))
            stack.enter_context(patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={
                    "applied_count": 0, "results": [],
                },
            ))
            stack.enter_context(patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={},
            ))
            stack.enter_context(patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={
                    "applied_count": 0, "results": [],
                },
            ))
            stack.enter_context(patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ))
            launch_store(
                store_name="Acme",
                include_legal_notice=True,
                include_subscription_policy=True,
                enable_welcome_discount=False,
                enable_collections=False,
            )
        kwargs = gen_mock.call_args.kwargs
        assert kwargs["include_legal_notice"] is True
        assert kwargs["include_subscription_policy"] is True

    def test_founder_name_forwards_to_pages(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={},
            ))
            stack.enter_context(patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={
                    "applied_count": 0, "results": [],
                },
            ))
            gen_mock = stack.enter_context(patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={},
            ))
            stack.enter_context(patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={
                    "applied_count": 0, "results": [],
                },
            ))
            stack.enter_context(patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ))
            launch_store(
                store_name="Acme",
                founder_name="Jane",
                enable_welcome_discount=False,
                enable_collections=False,
            )
        assert (
            gen_mock.call_args.kwargs["founder_name"]
            == "Jane"
        )
