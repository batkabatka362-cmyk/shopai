"""Tests for the Obsidian knowledge-vault exporter.

The exporter walks ShopAI's persistent state (engine→goal map,
GoalManager EMA, ApprovalQueue history) and writes a folder of
Markdown files with YAML frontmatter + wiki-links + tags.

Coverage:
  1. Engine pages — one per ENGINE_GOAL_MAP entry, with the
     primary goal as a wiki-link.
  2. Goal pages — one per canonical goal, surfacing EMA +
     sample count + aligned engines.
  3. Decision pages — one per EXECUTED / FAILED action in the
     approval queue, with deterministic filenames.
  4. Overview index — top-level dashboard referencing all three.
  5. Round-trip idempotency — running export twice produces the
     same files (deterministic per-source).
  6. Skipped-source diagnostics — when a source raises, the
     summary records it but the rest of the export proceeds.
  7. Helper functions — filename sanitisation, EMA/sample
     fallbacks, ISO timestamp formatting.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.knowledge import ExportSummary, ObsidianExporter
from core.knowledge.exporter import (
    _safe_filename,
    _safe_get_effectiveness,
    _safe_get_sample_count,
    _ts_iso,
)
from core.goals.goal_manager import GoalManager


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


@pytest.fixture
def fresh_manager() -> GoalManager:
    return GoalManager()


# ─── Helper functions ──────────────────────────────────────────


class TestSafeFilename:

    def test_alnum_passes_through(self):
        assert _safe_filename("appr_abc123") == "appr_abc123"

    def test_special_chars_replaced(self):
        # "appr/../etc" has 4 special chars (/, ., ., /) → 4 underscores
        assert _safe_filename("appr/../etc") == "appr____etc"

    def test_blank_returns_underscore(self):
        assert _safe_filename("") == "_"

    def test_non_string_returns_underscore(self):
        assert _safe_filename(None) == "_"  # type: ignore[arg-type]

    def test_hyphens_and_underscores_kept(self):
        assert _safe_filename("a-b_c.d") == "a-b_c_d"


class TestSafeGetEffectiveness:

    def test_returns_neutral_when_manager_none(self):
        assert _safe_get_effectiveness(None, "any") == 0.5

    def test_returns_neutral_when_manager_raises(self):
        mgr = MagicMock()
        mgr.get_effectiveness.side_effect = RuntimeError("boom")
        assert _safe_get_effectiveness(mgr, "any") == 0.5

    def test_returns_value_when_recorded(self, fresh_manager):
        for _ in range(3):
            fresh_manager.record_goal_outcome(
                "grow_customers",
                {"profit_delta": 5, "health_delta": 1},
            )
        eff = _safe_get_effectiveness(fresh_manager, "grow_customers")
        assert eff > 0.5


class TestSafeGetSampleCount:

    def test_zero_when_manager_none(self):
        assert _safe_get_sample_count(None, "any") == 0

    def test_returns_n_when_recorded(self, fresh_manager):
        fresh_manager.record_goal_outcome(
            "grow_customers", {"health_delta": 1},
        )
        fresh_manager.record_goal_outcome(
            "grow_customers", {"health_delta": 1},
        )
        assert _safe_get_sample_count(
            fresh_manager, "grow_customers",
        ) == 2

    def test_zero_for_unknown_goal(self, fresh_manager):
        assert _safe_get_sample_count(
            fresh_manager, "totally_unknown",
        ) == 0


class TestTsIso:

    def test_known_epoch(self):
        # 2026-05-15T00:00:00Z = 1778803200
        assert _ts_iso(1778803200) == "2026-05-15T00:00:00Z"

    def test_zero_falls_back(self):
        assert _ts_iso(0) == "0"

    def test_negative_falls_back(self):
        assert _ts_iso(-1) == "0"

    def test_non_numeric_falls_back(self):
        assert _ts_iso(None) == "0"
        assert _ts_iso("garbage") == "0"  # type: ignore[arg-type]


# ─── Engine pages ──────────────────────────────────────────────


class TestEnginePages:

    def test_one_file_per_engine(self, vault, fresh_manager):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        engines_dir = vault / "engines"
        assert engines_dir.is_dir()
        # Each ENGINE_GOAL_MAP entry produces a file
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        for engine in ENGINE_GOAL_MAP:
            assert (engines_dir / f"{engine}.md").exists()

    def test_frontmatter_and_wiki_link(self, vault, fresh_manager):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (vault / "engines" / "cart_recovery.md").read_text(
            encoding="utf-8",
        )
        # Frontmatter present
        assert content.startswith("---\n")
        assert "name: cart_recovery" in content
        assert "type: engine" in content
        assert "primary_goal: grow_customers" in content
        # Wiki-link to the goal
        assert "[[grow_customers]]" in content
        # Tag
        assert "#shopai/engine" in content
        assert "#shopai/goal/grow_customers" in content


# ─── Goal pages ────────────────────────────────────────────────


class TestGoalPages:

    def test_one_file_per_canonical_goal(self, vault, fresh_manager):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        goals_dir = vault / "goals"
        for goal in [
            "maximize_profit", "grow_customers", "increase_aov",
            "survive_crisis", "capture_opportunity",
        ]:
            assert (goals_dir / f"{goal}.md").exists()

    def test_effectiveness_neutral_when_no_data(
        self, vault, fresh_manager,
    ):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (vault / "goals" / "grow_customers.md").read_text(
            encoding="utf-8",
        )
        # Effectiveness in frontmatter renders as the neutral 0.500
        assert "effectiveness: 0.500" in content
        # Sample count 0 → label flips to no_data in the body
        assert "no_data" in content
        assert "Samples**: 0" in content

    def test_effectiveness_recorded_when_outcomes_logged(
        self, vault, fresh_manager,
    ):
        for _ in range(3):
            fresh_manager.record_goal_outcome(
                "maximize_profit",
                {"profit_delta": 5, "health_delta": 1},
            )
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (vault / "goals" / "maximize_profit.md").read_text(
            encoding="utf-8",
        )
        assert "Samples**: 3" in content
        # EMA bumped above neutral
        assert "effectiveness: 0.5" not in content.split(
            "\n## Triggers"
        )[0]
        assert "no_data" not in content

    def test_aligned_engines_listed(self, vault, fresh_manager):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (vault / "goals" / "grow_customers.md").read_text(
            encoding="utf-8",
        )
        # cart_recovery + loyalty + affiliate are all grow_customers
        assert "[[cart_recovery]]" in content
        assert "[[loyalty]]" in content
        assert "[[affiliate]]" in content


# ─── Decision pages ────────────────────────────────────────────


class TestDecisionPages:

    def test_no_decisions_when_queue_empty(
        self, vault, fresh_manager,
    ):
        # Patch the approval queue accessor to return an empty queue
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = []
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            summary = ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()
        assert summary.decisions == 0
        decisions_dir = vault / "decisions"
        assert decisions_dir.is_dir()
        assert list(decisions_dir.glob("*.md")) == []

    def test_one_file_per_executed_action(
        self, vault, fresh_manager,
    ):
        # Build a fake ApprovalAction-like object
        action = MagicMock()
        action.id = "appr_test_12345"
        action.engine = "cart_recovery"
        action.action_type = "mint_recovery_code"
        action.capability = "SHOPIFY_CREATE_DISCOUNT"
        action.narrative = "Recovery for user u1"
        status = MagicMock()
        status.value = "executed"
        action.status = status
        action.confidence = 0.85
        action.proposed_at = 1778803200  # 2026-05-15
        action.decided_at = 1778803260
        action.decided_by = "merchant"
        action.decision_reason = "looks good"

        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = [action]

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            summary = ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()

        assert summary.decisions == 1
        files = list((vault / "decisions").glob("*.md"))
        assert len(files) == 1
        # Filename starts with the date
        assert files[0].name.startswith("2026-05-15-cart_recovery-")
        content = files[0].read_text(encoding="utf-8")
        assert "status: executed" in content
        assert "engine: cart_recovery" in content
        assert "[[cart_recovery]]" in content
        assert "#shopai/decision/executed" in content
        assert "#shopai/engine/cart_recovery" in content

    def test_decision_limit_respected(
        self, vault, fresh_manager,
    ):
        # Confirm the decisions/ export uses ``decision_limit``.
        # The enrichment pass on engine pages also calls
        # ``list_executed`` (with a wider 500-limit window to
        # group per-engine recent activity), so we only assert
        # that the decisions/ call happened — not that it was
        # the ONLY call.
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = []
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
                decision_limit=50,
            ).export()
        fake_queue.list_executed.assert_any_call(limit=50)

    def test_filename_sanitises_engine_and_id(
        self, vault, fresh_manager,
    ):
        action = MagicMock()
        # Adversarial inputs
        action.id = "appr_../../etc"
        action.engine = "evil/engine"
        action.action_type = "x"
        action.capability = ""
        action.narrative = ""
        action.status = None
        action.confidence = None
        action.proposed_at = 1778803200
        action.decided_at = None
        action.decided_by = ""
        action.decision_reason = ""

        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = [action]

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()

        files = list((vault / "decisions").glob("*.md"))
        assert len(files) == 1
        # No slashes, no parent-traversal characters
        assert ".." not in files[0].name
        assert "/" not in files[0].name


# ─── Overview ──────────────────────────────────────────────────


class TestOverview:

    def test_overview_written(self, vault, fresh_manager):
        summary = ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        assert summary.overview_written
        overview = vault / "overview.md"
        assert overview.exists()
        content = overview.read_text(encoding="utf-8")
        assert "ShopAI knowledge vault" in content
        assert "#shopai/overview" in content


# ─── Source-failure isolation ──────────────────────────────────


class TestSourceFailureIsolation:

    def test_queue_failure_records_skip_but_writes_engines(
        self, vault, fresh_manager,
    ):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("db unavailable"),
        ):
            summary = ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()
        # Engines still wrote
        assert summary.engines > 0
        # Goals still wrote
        assert summary.goals == 5
        # Decisions skipped with diagnostic
        assert summary.decisions == 0
        assert any("decisions" in s for s in summary.skipped)


# ─── Idempotency ───────────────────────────────────────────────


class TestIdempotency:

    def test_second_run_produces_same_engine_files(
        self, vault, fresh_manager,
    ):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        first = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")

        # Run again
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        second = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")

        assert first == second

    def test_second_run_after_outcomes_refreshes_goal_ema(
        self, vault, fresh_manager,
    ):
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        before = (
            vault / "goals" / "grow_customers.md"
        ).read_text(encoding="utf-8")

        # Record outcomes between runs
        for _ in range(4):
            fresh_manager.record_goal_outcome(
                "grow_customers",
                {"profit_delta": 5, "health_delta": 1},
            )

        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        after = (
            vault / "goals" / "grow_customers.md"
        ).read_text(encoding="utf-8")

        # EMA value updated; the "no_data" marker is gone
        assert "no_data" in before
        assert "no_data" not in after
        assert "Samples**: 0" in before
        assert "Samples**: 4" in after


# ─── ExportSummary serialisation ───────────────────────────────


class TestExportSummarySerialization:

    def test_to_dict_round_trip(self):
        s = ExportSummary(
            engines=10, goals=5, decisions=3,
            overview_written=True, skipped=["x: err"],
        )
        d = s.to_dict()
        assert d["engines"] == 10
        assert d["goals"] == 5
        assert d["decisions"] == 3
        assert d["overview_written"] is True
        assert d["skipped"] == ["x: err"]
