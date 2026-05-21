"""Tests for ``engines.store_setup.launch_orchestrator``.

End-to-end ``launch_store`` runs the per-capability generators
and appliers (policies, pages) and returns a unified checklist.

Coverage:
  1. Empty store_name -> early-exit, not ready, no apply calls.
  2. All steps succeed -> ready_to_launch=True + populated
     checklist.
  3. Policies step fails -> pages still attempts; ready_to_launch
     is False.
  4. Pages step fails -> policies still recorded; ready_to_launch
     is False.
  5. Rollup writeback recording.
  6. store_id propagates to each sub-call.
  7. Underlying module raises -> per-step error captured, the
     other step still attempts.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.store_setup.launch_orchestrator import launch_store


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
        # Neither applier ever invoked
        p_apply.assert_not_called()
        page_apply.assert_not_called()

    def test_whitespace_only(self):
        result = launch_store(store_name="   ")
        assert result["ready_to_launch"] is False


class TestAllSuccess:

    def test_full_launch_path(self):
        policies_dict = {
            "REFUND_POLICY": "r",
            "PRIVACY_POLICY": "p",
        }
        pages_dict = {
            "About": "<h1>About</h1>",
            "Contact": "<h1>Contact</h1>",
        }
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value=policies_dict,
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={
                "applied_count": 2,
                "results": [
                    {"policy_type": "REFUND_POLICY",
                     "ok": True, "error": None},
                    {"policy_type": "PRIVACY_POLICY",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value=pages_dict,
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={
                "applied_count": 2,
                "results": [
                    {"title": "About", "handle": "about",
                     "ok": True, "error": None},
                    {"title": "Contact", "handle": "contact",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            result = launch_store(
                store_name="Acme",
                niche="beauty",
            )
        assert result["ready_to_launch"] is True
        assert result["policies"]["applied_count"] == 2
        assert result["pages"]["applied_count"] == 2
        # Checklist has both steps as OK
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["policies"]["ok"] is True
        assert steps["policies"]["applied"] == 2
        assert steps["pages"]["ok"] is True
        assert steps["pages"]["applied"] == 2

    def test_rollup_writeback_recorded(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4, "results": [],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(store_name="Acme")
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "store_setup"
        assert kwargs["action_type"] == "launch_store"
        assert kwargs["capability"] == "SHOPAI_LAUNCH_STORE"
        assert kwargs["success"] is True
        assert kwargs["metrics"]["policies_applied"] == 1
        assert kwargs["metrics"]["pages_applied"] == 1
        assert kwargs["metrics"]["discount_applied"] == 1
        assert kwargs["metrics"]["collections_applied"] == 4


class TestPartialFailure:

    def test_policies_fail_pages_succeed(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={
                "applied_count": 0,
                "results": [
                    {"policy_type": "REFUND_POLICY",
                     "ok": False, "error": "rejected"},
                ],
            },
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            result = launch_store(store_name="Acme")
        assert result["ready_to_launch"] is False
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["policies"]["ok"] is False
        assert steps["pages"]["ok"] is True

    def test_pages_fail_policies_succeed(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={
                "applied_count": 0,
                "results": [
                    {"title": "About", "handle": "about",
                     "ok": False, "error": "duplicate"},
                ],
            },
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            result = launch_store(store_name="Acme")
        assert result["ready_to_launch"] is False


class TestModuleException:

    def test_policy_step_raise_doesnt_block_pages(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            side_effect=RuntimeError("generator broken"),
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            result = launch_store(store_name="Acme")
        # Policies step captured error, pages still completed
        assert "generator broken" in result["policies"]["error"]
        assert result["pages"]["applied_count"] == 1
        assert result["ready_to_launch"] is False

    def test_pages_step_raise_doesnt_block_policies(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            side_effect=RuntimeError("generator broken"),
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            result = launch_store(store_name="Acme")
        assert result["policies"]["applied_count"] == 1
        assert "generator broken" in result["pages"]["error"]


class TestStoreIdPropagation:

    def test_store_id_threads_through(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={"applied_count": 1, "results": []},
        ) as policy_mock, patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={"applied_count": 1, "results": []},
        ) as page_mock, patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ) as discount_mock, patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={"applied_count": 4, "results": []},
        ) as coll_mock, patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(
                store_name="Acme",
                store_id="store-a",
            )
        # Each sub-applier got store_id kwarg
        assert (
            policy_mock.call_args.kwargs["store_id"]
            == "store-a"
        )
        assert (
            page_mock.call_args.kwargs["store_id"]
            == "store-a"
        )
        assert (
            discount_mock.call_args.kwargs["store_id"]
            == "store-a"
        )
        assert (
            coll_mock.call_args.kwargs["store_id"]
            == "store-a"
        )
        # Rollup recording also carries store_id
        assert (
            record_mock.call_args.kwargs["params"][
                "store_id"
            ] == "store-a"
        )


class TestOptionalFlags:

    def test_legal_notice_and_subscription_flags_forward(self):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
        ) as gen_mock, patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={"applied_count": 0, "results": []},
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={"applied_count": 0, "results": []},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            gen_mock.return_value = {}
            launch_store(
                store_name="Acme",
                include_legal_notice=True,
                include_subscription_policy=True,
            )
        kwargs = gen_mock.call_args.kwargs
        assert kwargs["include_legal_notice"] is True
        assert kwargs["include_subscription_policy"] is True

    def test_founder_name_forwards_to_pages(self):
        with patch(
            "engines.store_setup.page_generator.generate_pages",
        ) as gen_mock, patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value={"applied_count": 0, "results": []},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value={"applied_count": 0, "results": []},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4,
                "results": [
                    {"title": "Featured", "handle": "featured",
                     "ok": True, "error": None},
                    {"title": "New",      "handle": "new",
                     "ok": True, "error": None},
                    {"title": "Bestsellers", "handle": "bestsellers",
                     "ok": True, "error": None},
                    {"title": "Sale",     "handle": "sale",
                     "ok": True, "error": None},
                ],
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            gen_mock.return_value = {}
            launch_store(
                store_name="Acme",
                founder_name="Jane",
            )
        assert (
            gen_mock.call_args.kwargs["founder_name"]
            == "Jane"
        )


# ─── Discount + collections fan-out (added when the orchestrator
#     grew from 2 steps to 4) ─────────────────────────────────


class TestDiscountStep:
    """The orchestrator's third step calls
    ``welcome_discount.generate`` then ``apply``. A successful
    application contributes to ``ready_to_launch``."""

    def _patch_first_two_steps_ok(self):
        return (
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier.apply_policies",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.page_generator.generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={"applied_count": 4, "results": []},
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        )

    def test_discount_success_contributes_to_ready(self):
        patches = self._patch_first_two_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ):
            result = launch_store(
                store_name="Acme", niche="beauty",
            )
        assert result["ready_to_launch"] is True
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["discount"]["ok"] is True
        assert steps["discount"]["applied"] == 1
        assert result["discount"]["code"] == "WELCOME15"

    def test_discount_failure_blocks_ready(self):
        patches = self._patch_first_two_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": False, "code": None,
                "percentage": None, "error": "duplicate_code",
            },
        ):
            result = launch_store(store_name="Acme")
        assert result["ready_to_launch"] is False
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["discount"]["ok"] is False
        assert steps["discount"]["error"] == "duplicate_code"

    def test_discount_module_raise_captured(self):
        patches = self._patch_first_two_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.welcome_discount."
            "generate_welcome_discount",
            side_effect=RuntimeError("welcome broken"),
        ):
            result = launch_store(store_name="Acme")
        assert "welcome broken" in result["discount"]["error"]
        assert result["ready_to_launch"] is False
        # Other steps still completed
        assert result["policies"]["applied_count"] == 1
        assert result["pages"]["applied_count"] == 1


class TestCollectionsStep:

    def _patch_first_three_steps_ok(self):
        return (
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier.apply_policies",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.page_generator.generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={
                    "applied": True, "code": "WELCOME15",
                    "percentage": 15, "error": None,
                },
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        )

    def test_collections_success_contributes_to_ready(self):
        patches = self._patch_first_three_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4, "results": [],
            },
        ):
            result = launch_store(
                store_name="Acme", niche="beauty",
            )
        assert result["ready_to_launch"] is True
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["collections"]["ok"] is True
        assert steps["collections"]["applied"] == 4

    def test_collections_zero_blocks_ready(self):
        patches = self._patch_first_three_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={"applied_count": 0, "results": []},
        ):
            result = launch_store(store_name="Acme")
        assert result["ready_to_launch"] is False
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["collections"]["ok"] is False

    def test_collections_module_raise_captured(self):
        patches = self._patch_first_three_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            side_effect=RuntimeError("seeder broken"),
        ):
            result = launch_store(store_name="Acme")
        assert "seeder broken" in result["collections"]["error"]
        assert result["ready_to_launch"] is False


class TestBrandStep:
    """Brand assets are OPTIONAL: when no URLs are supplied the
    step is recorded as ``skipped=True, ok=True`` so it doesn't
    block ``ready_to_launch``. When URLs ARE supplied the step
    runs and the uploader's own ok/error flow drives the
    checklist entry."""

    def _patch_first_four_steps_ok(self):
        return (
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier.apply_policies",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.page_generator.generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={
                    "applied": True, "code": "WELCOME15",
                    "percentage": 15, "error": None,
                },
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={"applied_count": 4, "results": []},
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        )

    def test_no_urls_skips_brand_step_still_ready(self):
        """Default-args launch (no URLs) -> brand step is
        skipped and ``ready_to_launch`` stays True."""
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
        ) as brand_mock:
            result = launch_store(store_name="Acme")
        # Uploader was NEVER called -- no URLs provided
        brand_mock.assert_not_called()
        assert result["brand"]["skipped"] is True
        assert result["brand"]["uploaded_count"] == 0
        # Checklist entry exists with ok=True (skip != failure)
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["brand"]["ok"] is True
        assert steps["brand"]["skipped"] is True
        # And the launch is still ready
        assert result["ready_to_launch"] is True

    def test_urls_provided_runs_uploader(self):
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 2,
                "files": [
                    {"asset": "logo"}, {"asset": "favicon"},
                ],
                "missing_assets": ["hero", "og_image"],
                "ok": True,
                "error": None,
            },
        ) as brand_mock:
            result = launch_store(
                store_name="Acme",
                logo_url="https://x/logo.png",
                favicon_url="https://x/favicon.png",
            )
        brand_mock.assert_called_once()
        kwargs = brand_mock.call_args.kwargs
        assert kwargs["logo_url"] == "https://x/logo.png"
        assert kwargs["favicon_url"] == "https://x/favicon.png"
        assert result["brand"]["skipped"] is False
        assert result["brand"]["uploaded_count"] == 2
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["brand"]["ok"] is True
        assert steps["brand"]["applied"] == 2
        assert result["ready_to_launch"] is True

    def test_uploader_failure_blocks_ready(self):
        """When URLs were provided but the uploader returned
        ok=False (e.g. logo+favicon didn't both upload), the
        brand step counts as a failure and blocks
        ready_to_launch."""
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 1,
                "files": [{"asset": "logo"}],
                "missing_assets": ["favicon"],
                "ok": False,
                "error": "favicon_upload_rejected",
            },
        ):
            result = launch_store(
                store_name="Acme",
                logo_url="https://x/logo.png",
            )
        assert result["brand"]["ok"] is False
        assert result["brand"]["skipped"] is False
        assert result["ready_to_launch"] is False
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["brand"]["ok"] is False

    def test_uploader_module_raise_captured(self):
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            side_effect=RuntimeError("uploader broken"),
        ):
            result = launch_store(
                store_name="Acme",
                logo_url="https://x/logo.png",
            )
        assert "uploader broken" in result["brand"]["error"]
        assert result["brand"]["skipped"] is False
        assert result["ready_to_launch"] is False

    def test_partial_url_set_still_runs_uploader(self):
        """Even just one URL (e.g. only hero) should trigger
        the step -- the uploader itself decides whether the
        minimum set is met."""
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 1,
                "files": [{"asset": "hero"}],
                "missing_assets": ["logo", "favicon", "og_image"],
                "ok": False,
                "error": "missing_required: logo, favicon",
            },
        ) as brand_mock:
            launch_store(
                store_name="Acme",
                hero_url="https://x/hero.png",
            )
        brand_mock.assert_called_once()
        kwargs = brand_mock.call_args.kwargs
        assert kwargs["hero_url"] == "https://x/hero.png"
        assert kwargs["logo_url"] is None
        assert kwargs["favicon_url"] is None

    def test_rollup_metrics_carry_brand(self):
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 4,
                "files": [],
                "missing_assets": [],
                "ok": True,
                "error": None,
            },
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(
                store_name="Acme",
                logo_url="https://x/l.png",
                favicon_url="https://x/f.png",
                hero_url="https://x/h.png",
                og_image_url="https://x/og.png",
            )
        kwargs = record_mock.call_args.kwargs
        assert kwargs["metrics"]["brand_uploaded"] == 4
        assert kwargs["metrics"]["brand_skipped"] is False
        assert kwargs["success"] is True

    def test_skip_recorded_in_rollup(self):
        """When the step is skipped, the rollup metrics
        explicitly say so -- so the Phase 8 learning loop can
        tell apart "no brand URLs supplied" from "brand
        failed"."""
        patches = self._patch_first_four_steps_ok()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(store_name="Acme")
        kwargs = record_mock.call_args.kwargs
        assert kwargs["metrics"]["brand_uploaded"] == 0
        assert kwargs["metrics"]["brand_skipped"] is True
        # Skip doesn't block ready_to_launch
        assert kwargs["success"] is True


class TestDesignStep:
    """Step 6: design tokens via StoreDesignEngine +
    apply_design.

    Optional: if no MAIN theme exists yet, the step is
    skipped and contributes ok=True to ready_to_launch (the
    operator hasn't installed a theme; a dev-store launch is
    still valid). When a MAIN theme exists, the engine runs
    and the apply result drives the checklist.
    """

    def _patch_first_five_steps_ok(self):
        return (
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1, "results": []},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={
                    "applied": True, "code": "WELCOME15",
                    "percentage": 15, "error": None,
                },
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={"applied_count": 4, "results": []},
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        )

    def test_no_main_theme_skips_step_still_ready(self):
        from unittest.mock import MagicMock
        patches = self._patch_first_five_steps_ok()
        router = MagicMock()
        themes_result = MagicMock()
        themes_result.ok = True
        themes_result.data = {"themes": []}
        router.execute.return_value = themes_result
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "core.adapters.get_router", return_value=router,
        ):
            result = launch_store(store_name="Acme")
        assert result["design"]["skipped"] is True
        assert result["design"]["error"] == "no_main_theme"
        # Skip -> contributes ok=True -> launch is ready
        assert result["ready_to_launch"] is True
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["design"]["ok"] is True
        assert steps["design"]["skipped"] is True

    def test_themes_call_fails_skips_step(self):
        from unittest.mock import MagicMock
        patches = self._patch_first_five_steps_ok()
        router = MagicMock()
        themes_result = MagicMock()
        themes_result.ok = False
        themes_result.error = "access denied"
        router.execute.return_value = themes_result
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "core.adapters.get_router", return_value=router,
        ):
            result = launch_store(store_name="Acme")
        # main_theme_id stays "" -> no_main_theme,
        # skipped stays True from default
        assert result["design"]["skipped"] is True
        assert result["ready_to_launch"] is True

    def test_engine_failure_marks_error_not_skipped(self):
        from unittest.mock import MagicMock
        patches = self._patch_first_five_steps_ok()
        router = MagicMock()
        themes_result = MagicMock()
        themes_result.ok = True
        themes_result.data = {"themes": [
            {"id": "gid://shopify/OnlineStoreTheme/1",
             "role": "MAIN"},
        ]}
        router.execute.return_value = themes_result
        engine_cls = MagicMock()
        engine_cls.return_value.run.return_value = {
            "status": "error",
            "data": {},
            "error": "missing brand",
        }
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
            engine_cls,
        ):
            result = launch_store(store_name="Acme")
        assert result["design"]["applied"] is False
        assert result["design"]["skipped"] is False
        assert "engine" in (result["design"]["error"] or "")
        assert result["ready_to_launch"] is False

    def test_success_path_drives_checklist(self):
        from unittest.mock import MagicMock
        patches = self._patch_first_five_steps_ok()
        router = MagicMock()
        themes_result = MagicMock()
        themes_result.ok = True
        themes_result.data = {"themes": [
            {"id": "gid://shopify/OnlineStoreTheme/1",
             "role": "MAIN"},
        ]}
        router.execute.return_value = themes_result
        engine_cls = MagicMock()
        engine_cls.return_value.run.return_value = {
            "status": "success",
            "data": {"color_palette": {"primary": "#000"}},
            "error": None,
        }
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
            engine_cls,
        ), patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": True,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [
                    "assets/shopai-design-tokens.json",
                    "snippets/shopai-design.liquid",
                ],
                "error": None,
            },
        ):
            result = launch_store(store_name="Acme")
        assert result["design"]["applied"] is True
        assert result["design"]["skipped"] is False
        assert len(result["design"]["files_written"]) == 2
        assert result["ready_to_launch"] is True
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["design"]["ok"] is True
        assert steps["design"]["applied"] == 2

    def test_rollup_metrics_carry_design(self):
        from unittest.mock import MagicMock
        patches = self._patch_first_five_steps_ok()
        router = MagicMock()
        themes_result = MagicMock()
        themes_result.ok = True
        themes_result.data = {"themes": []}
        router.execute.return_value = themes_result
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(store_name="Acme")
        kwargs = record_mock.call_args.kwargs
        assert kwargs["metrics"]["design_applied"] is False
        assert kwargs["metrics"]["design_skipped"] is True
