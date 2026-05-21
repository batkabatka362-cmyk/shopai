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

from unittest.mock import MagicMock, patch

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
            "generate_welcome_discount",
            return_value={"code": "WELCOME15", "percentage": 15},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME15",
                "percentage": 15, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[{"title": "New Arrivals",
                           "handle": "new-arrivals"}],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={
                "applied_count": 4, "results": [],
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
        assert result["discount"]["applied"] is True
        assert result["collections"]["applied_count"] == 4
        # Checklist has all 4 steps as OK
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["policies"]["ok"] is True
        assert steps["policies"]["applied"] == 2
        assert steps["pages"]["ok"] is True
        assert steps["pages"]["applied"] == 2
        assert steps["discount"]["ok"] is True
        assert steps["collections"]["ok"] is True
        assert steps["collections"]["applied"] == 4

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
            "generate_welcome_discount",
            return_value={"code": "WELCOME10", "percentage": 10},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME10",
                "percentage": 10, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[{"title": "New Arrivals",
                           "handle": "new-arrivals"}],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={"applied_count": 4, "results": []},
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


class TestDiscountStep:
    """Welcome discount as Step 3 of the launch pipeline."""

    def _patches(self, **overrides):
        """Build the standard set of patches with sensible
        defaults that callers can override per-test."""
        defaults = {
            "policies_apply": {"applied_count": 1, "results": []},
            "pages_apply": {"applied_count": 1, "results": []},
            "discount_apply": {
                "applied": True, "code": "WELCOME10",
                "percentage": 10, "error": None,
            },
            "collections_apply": {
                "applied_count": 1, "results": [],
            },
        }
        defaults.update(overrides)
        return defaults

    def _run(self, defaults):
        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            return_value={"REFUND_POLICY": "r"},
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            return_value=defaults["policies_apply"],
        ), patch(
            "engines.store_setup.page_generator.generate_pages",
            return_value={"About": "<h1>x</h1>"},
        ), patch(
            "engines.store_setup.page_applier.apply_pages",
            return_value=defaults["pages_apply"],
        ), patch(
            "engines.store_setup.welcome_discount."
            "generate_welcome_discount",
            return_value={"code": "WELCOME10", "percentage": 10},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value=defaults["discount_apply"],
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[{"title": "x", "handle": "x"}],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value=defaults["collections_apply"],
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            return launch_store(store_name="Acme")

    def test_discount_success_marks_step_ok(self):
        result = self._run(self._patches())
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["discount"]["ok"] is True
        assert result["discount"]["code"] == "WELCOME10"

    def test_discount_failure_blocks_ready(self):
        result = self._run(self._patches(
            discount_apply={
                "applied": False, "code": None,
                "percentage": None, "error": "router_unavailable",
            },
        ))
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["discount"]["ok"] is False
        assert "router_unavailable" in (
            steps["discount"]["error"] or ""
        )
        assert result["ready_to_launch"] is False

    def test_discount_raise_captured(self):
        # Make the module-level import succeed but apply raise
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
            "generate_welcome_discount",
            side_effect=RuntimeError("boom"),
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={"applied_count": 0, "results": []},
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            result = launch_store(store_name="Acme")
        assert "boom" in result["discount"]["error"]


class TestCollectionsStep:
    """Starter collections as Step 4 of the launch pipeline."""

    def _run(self, *, collections_apply):
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
            "generate_welcome_discount",
            return_value={"code": "WELCOME10", "percentage": 10},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "WELCOME10",
                "percentage": 10, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[{"title": "x", "handle": "x"}],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value=collections_apply,
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ):
            return launch_store(store_name="Acme")

    def test_collections_success_marks_step_ok(self):
        result = self._run(collections_apply={
            "applied_count": 4, "results": [],
        })
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["collections"]["ok"] is True
        assert steps["collections"]["applied"] == 4
        assert result["ready_to_launch"] is True

    def test_collections_zero_count_blocks_ready(self):
        result = self._run(collections_apply={
            "applied_count": 0, "results": [],
        })
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["collections"]["ok"] is False
        assert result["ready_to_launch"] is False


class TestBrandStep:
    """Brand assets as OPTIONAL Step 5.

    No URLs supplied -> skipped=True, contributes ok=True to
    the checklist (doesn't block ready_to_launch).
    URLs supplied + success -> ok=True, applied counts.
    URLs supplied + failure -> ok=False, blocks ready.
    """

    def _common_patches(self, *, brand_result=None,
                        brand_side_effect=None):
        patches = [
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "generate_welcome_discount",
                return_value={"code": "WELCOME10",
                              "percentage": 10},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={
                    "applied": True, "code": "WELCOME10",
                    "percentage": 10, "error": None,
                },
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "generate_starter_collections",
                return_value=[{"title": "x", "handle": "x"}],
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        ]
        if brand_side_effect is not None:
            patches.append(patch(
                "engines.store_setup.brand_uploader."
                "upload_brand_assets",
                side_effect=brand_side_effect,
            ))
        elif brand_result is not None:
            patches.append(patch(
                "engines.store_setup.brand_uploader."
                "upload_brand_assets",
                return_value=brand_result,
            ))
        return patches

    def test_no_urls_skipped_doesnt_block(self):
        # No brand_uploader patch needed: the step
        # short-circuits before importing it when all URLs are
        # None.
        patches = self._common_patches()
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], \
                patches[7], patches[8]:
            result = launch_store(store_name="Acme")
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["brand"]["ok"] is True
        assert steps["brand"]["skipped"] is True
        assert steps["brand"]["applied"] == 0
        # All other steps OK + brand skipped -> ready
        assert result["ready_to_launch"] is True
        assert result["brand"]["skipped"] is True

    def test_urls_supplied_success(self):
        brand_ok = {
            "uploaded_count": 2,
            "files": [
                {"file_id": "gid://f/1", "alt": "logo"},
                {"file_id": "gid://f/2", "alt": "favicon"},
            ],
            "missing_assets": [],
            "ok": True,
            "error": None,
        }
        patches = self._common_patches(brand_result=brand_ok)
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], \
                patches[7], patches[8], patches[9]:
            result = launch_store(
                store_name="Acme",
                logo_url="https://cdn/logo.png",
                favicon_url="https://cdn/favicon.ico",
            )
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["brand"]["ok"] is True
        assert steps["brand"]["skipped"] is False
        assert steps["brand"]["applied"] == 2
        assert result["ready_to_launch"] is True

    def test_urls_supplied_failure_blocks(self):
        brand_fail = {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": ["logo", "favicon"],
            "ok": False,
            "error": "router_unavailable",
        }
        patches = self._common_patches(brand_result=brand_fail)
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], \
                patches[7], patches[8], patches[9]:
            result = launch_store(
                store_name="Acme",
                logo_url="https://cdn/logo.png",
            )
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["brand"]["ok"] is False
        assert steps["brand"]["skipped"] is False
        assert result["ready_to_launch"] is False
        assert "router_unavailable" in (
            result["brand"]["error"] or ""
        )

    def test_brand_uploader_raise_captured(self):
        patches = self._common_patches(
            brand_side_effect=RuntimeError("boom"),
        )
        with patches[0], patches[1], patches[2], patches[3], \
                patches[4], patches[5], patches[6], \
                patches[7], patches[8], patches[9]:
            result = launch_store(
                store_name="Acme",
                logo_url="https://cdn/logo.png",
            )
        assert "boom" in result["brand"]["error"]
        assert result["ready_to_launch"] is False

    def test_rollup_carries_brand_metrics(self):
        brand_ok = {
            "uploaded_count": 2, "files": [],
            "missing_assets": [], "ok": True, "error": None,
        }
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
            "generate_welcome_discount",
            return_value={"code": "W", "percentage": 10},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "W",
                "percentage": 10, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[{"title": "x", "handle": "x"}],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value=brand_ok,
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(
                store_name="Acme",
                logo_url="https://cdn/logo.png",
            )
        m = record_mock.call_args.kwargs["metrics"]
        assert m["brand_uploaded"] == 2
        assert m["brand_skipped"] is False


class TestDesignStep:
    """Design tokens as OPTIONAL Step 6.

    No MAIN theme found -> skipped=True, contributes ok=True
    (doesn't block ready_to_launch).
    MAIN theme + engine + applier all succeed -> applied=True.
    Engine returns non-success -> step records error (no
    skip), blocks ready.
    Applier fails -> step records error, blocks ready.
    Outer raise -> step records error, blocks ready.
    """

    def _common(self):
        """Patches for the mandatory upstream steps."""
        return [
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "generate_welcome_discount",
                return_value={"code": "WELCOME10",
                              "percentage": 10},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={
                    "applied": True, "code": "WELCOME10",
                    "percentage": 10, "error": None,
                },
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "generate_starter_collections",
                return_value=[{"title": "x", "handle": "x"}],
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        ]

    def test_no_main_theme_step_skipped(self):
        """Router returns no MAIN theme -> step skipped,
        doesn't block readiness."""
        from types import SimpleNamespace
        themes_result = SimpleNamespace(
            ok=True, data={"themes": []}, error=None,
        )
        router = type("R", (), {})()
        router.execute = lambda cap, params: themes_result
        with self._common()[0], self._common()[1], \
                self._common()[2], self._common()[3], \
                self._common()[4], self._common()[5], \
                self._common()[6], self._common()[7], \
                self._common()[8], patch(
            "core.adapters.get_router", return_value=router,
        ):
            result = launch_store(store_name="Acme")
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["design"]["ok"] is True
        assert steps["design"]["skipped"] is True
        assert "no_main_theme" in (
            result["design"]["error"] or ""
        )
        # Mandatory + brand-skipped + design-skipped -> ready
        assert result["ready_to_launch"] is True

    def test_themes_call_fails_step_skipped(self):
        """SHOPIFY_LIST_THEMES returning ok=False resolves to
        skipped (no_main_theme)."""
        from types import SimpleNamespace
        themes_result = SimpleNamespace(
            ok=False, data=None, error="x",
        )
        router = type("R", (), {})()
        router.execute = lambda cap, params: themes_result
        with self._common()[0], self._common()[1], \
                self._common()[2], self._common()[3], \
                self._common()[4], self._common()[5], \
                self._common()[6], self._common()[7], \
                self._common()[8], patch(
            "core.adapters.get_router", return_value=router,
        ):
            result = launch_store(store_name="Acme")
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["design"]["skipped"] is True
        assert steps["design"]["ok"] is True

    def test_engine_failure_marks_error_not_skipped(self):
        """MAIN theme found but design engine returned non-
        success -> step records error, NOT skipped."""
        from types import SimpleNamespace
        themes_result = SimpleNamespace(
            ok=True,
            data={"themes": [{
                "id": "gid://shopify/OnlineStoreTheme/1",
                "role": "MAIN",
            }]},
            error=None,
        )
        router = type("R", (), {})()
        router.execute = lambda cap, params: themes_result
        engine_mock = MagicMock()
        engine_mock.run.return_value = {
            "status": "error", "data": {}, "meta": {},
            "error": "engine_broken",
        }
        with self._common()[0], self._common()[1], \
                self._common()[2], self._common()[3], \
                self._common()[4], self._common()[5], \
                self._common()[6], self._common()[7], \
                self._common()[8], patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
            return_value=engine_mock,
        ):
            result = launch_store(store_name="Acme")
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["design"]["skipped"] is False
        assert steps["design"]["ok"] is False
        assert "engine_broken" in result["design"]["error"]
        assert result["ready_to_launch"] is False

    def test_full_success_path(self):
        from types import SimpleNamespace
        themes_result = SimpleNamespace(
            ok=True,
            data={"themes": [{
                "id": "gid://shopify/OnlineStoreTheme/1",
                "role": "MAIN",
            }]},
            error=None,
        )
        router = type("R", (), {})()
        router.execute = lambda cap, params: themes_result
        engine_mock = MagicMock()
        engine_mock.run.return_value = {
            "status": "success",
            "data": {"brand": {}, "products": [],
                     "analytics": {}},
            "meta": {}, "error": None,
        }
        applier_result = {
            "applied": True,
            "theme_id": "gid://shopify/OnlineStoreTheme/1",
            "files_written": [
                "assets/shopai-design-tokens.json",
                "snippets/shopai-design.liquid",
            ],
            "error": None,
        }
        with self._common()[0], self._common()[1], \
                self._common()[2], self._common()[3], \
                self._common()[4], self._common()[5], \
                self._common()[6], self._common()[7], \
                self._common()[8], patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
            return_value=engine_mock,
        ), patch(
            "engines.store_design.design_applier.apply_design",
            return_value=applier_result,
        ):
            result = launch_store(store_name="Acme")
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["design"]["ok"] is True
        assert steps["design"]["skipped"] is False
        assert steps["design"]["applied"] == 1
        assert result["design"]["applied"] is True
        assert len(result["design"]["files_written"]) == 2
        assert result["ready_to_launch"] is True

    def test_rollup_carries_design_metrics(self):
        from types import SimpleNamespace
        themes_result = SimpleNamespace(
            ok=True, data={"themes": []}, error=None,
        )
        router = type("R", (), {})()
        router.execute = lambda cap, params: themes_result
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
            "generate_welcome_discount",
            return_value={"code": "W", "percentage": 10},
        ), patch(
            "engines.store_setup.welcome_discount."
            "apply_welcome_discount",
            return_value={
                "applied": True, "code": "W",
                "percentage": 10, "error": None,
            },
        ), patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            return_value=[{"title": "x", "handle": "x"}],
        ), patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(store_name="Acme")
        m = record_mock.call_args.kwargs["metrics"]
        assert "design_applied" in m
        assert "design_skipped" in m
        assert m["design_applied"] == 0
        assert m["design_skipped"] is True


class TestProductsStep:
    """Product seeder as OPTIONAL Step 7.

    seed_products=False (default) -> skipped=True, doesn't
    block ready_to_launch.
    seed_products=True + apply succeeds -> step ok.
    seed_products=True + apply fails -> step ok=False,
    blocks ready_to_launch.
    """

    def _upstream_patches(self):
        return [
            patch(
                "engines.store_setup.policy_generator."
                "generate_policies",
                return_value={"REFUND_POLICY": "r"},
            ),
            patch(
                "engines.store_setup.policy_applier."
                "apply_policies",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.page_generator."
                "generate_pages",
                return_value={"About": "<h1>x</h1>"},
            ),
            patch(
                "engines.store_setup.page_applier.apply_pages",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "generate_welcome_discount",
                return_value={"code": "W", "percentage": 10},
            ),
            patch(
                "engines.store_setup.welcome_discount."
                "apply_welcome_discount",
                return_value={
                    "applied": True, "code": "W",
                    "percentage": 10, "error": None,
                },
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "generate_starter_collections",
                return_value=[{"title": "x", "handle": "x"}],
            ),
            patch(
                "engines.store_setup.collection_seeder."
                "apply_starter_collections",
                return_value={"applied_count": 1,
                              "results": []},
            ),
            patch(
                "engines.store_setup.launch_orchestrator."
                "record_writeback",
            ),
        ]

    def test_default_skipped_doesnt_block(self):
        p = self._upstream_patches()
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], \
                p[7], p[8]:
            result = launch_store(store_name="Acme")
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["products"]["ok"] is True
        assert steps["products"]["skipped"] is True
        assert steps["products"]["applied"] == 0
        # Mandatory steps ok + optional all skipped -> ready
        assert result["ready_to_launch"] is True

    def test_opt_in_success_marks_step_ok(self):
        p = self._upstream_patches()
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], \
                p[7], p[8], patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=[
                {"title": "X", "handle": "x"},
                {"title": "Y", "handle": "y"},
                {"title": "Z", "handle": "z"},
                {"title": "Q", "handle": "q"},
            ],
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
            return_value={"applied_count": 4, "results": []},
        ):
            result = launch_store(
                store_name="Acme", seed_products=True,
            )
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["products"]["ok"] is True
        assert steps["products"]["skipped"] is False
        assert steps["products"]["applied"] == 4
        assert result["ready_to_launch"] is True

    def test_opt_in_failure_blocks_ready(self):
        p = self._upstream_patches()
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], \
                p[7], p[8], patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=[
                {"title": "X", "handle": "x"},
            ],
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
            return_value={"applied_count": 0, "results": []},
        ):
            result = launch_store(
                store_name="Acme", seed_products=True,
            )
        steps = {c["step"]: c for c in result["checklist"]}
        assert steps["products"]["ok"] is False
        assert steps["products"]["skipped"] is False
        assert result["ready_to_launch"] is False

    def test_opt_in_raise_captured(self):
        p = self._upstream_patches()
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], \
                p[7], p[8], patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            side_effect=RuntimeError("boom"),
        ):
            result = launch_store(
                store_name="Acme", seed_products=True,
            )
        assert "boom" in (result["products"]["error"] or "")
        assert result["ready_to_launch"] is False

    def test_rollup_carries_products_metrics(self):
        p = self._upstream_patches()
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], \
                p[7], patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=[{"title": "X", "handle": "x"}],
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
            return_value={"applied_count": 1, "results": []},
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "record_writeback",
        ) as record_mock:
            launch_store(
                store_name="Acme", seed_products=True,
            )
        m = record_mock.call_args.kwargs["metrics"]
        assert "products_seeded" in m
        assert "products_skipped" in m
        assert m["products_seeded"] == 1
        assert m["products_skipped"] is False
