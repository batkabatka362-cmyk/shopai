"""Dashboard vault search — Option K.

Exercises ``GET /api/vault/search`` and its ``_collect_vault_search``
helper. The search walks the real vault root on disk, so the tests
seed a throwaway directory and redirect the config lookup at it.

Coverage:

* Scoring — title > frontmatter/tag > body; irrelevant notes dropped.
* Folder filter — ``type=Wins`` narrows the walk; unknown types
  gracefully fall back to the whole vault (so the UI never 500s on a
  typo in a chip label).
* Empty query — returns a newest-first browse listing rather than 0
  results, so the sidebar is useful even before you type.
* Safety — snippet window bounded, oversized bodies clipped, missing
  vault surfaces a clean "not configured" envelope instead of an
  exception.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _collect_vault_search,
)


def _handler(query: str = "") -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = "/api/vault/search" + (("?" + query) if query else "")
    return h


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
    """Seed a small vault with notes we can rank against."""
    (tmp_path / "Wins").mkdir()
    (tmp_path / "Errors").mkdir()
    (tmp_path / "Decisions").mkdir()
    (tmp_path / "ShopAI" / "Learned").mkdir(parents=True)

    (tmp_path / "Wins" / "shopify-checkout-recovered.md").write_text(
        "# Shopify checkout recovered\n\nFixed a flaky checkout flow.\n",
        encoding="utf-8",
    )
    (tmp_path / "Wins" / "vault-indexing.md").write_text(
        "---\ntitle: Vault indexing\ntags: [performance, search]\n---\n\n"
        "Body mentions checkout once.\n",
        encoding="utf-8",
    )
    (tmp_path / "Errors" / "rate-limit.md").write_text(
        "---\ntitle: Rate limit\ntags: [shopify, api]\n---\n\n"
        "Shopify rate-limited us on checkout endpoint.\n",
        encoding="utf-8",
    )
    (tmp_path / "Decisions" / "pick-obsidian.md").write_text(
        "# Pick Obsidian\n\nMemory system decision.\n",
        encoding="utf-8",
    )
    (tmp_path / "ShopAI" / "Learned" / "pattern.md").write_text(
        "Learned pattern body.\n", encoding="utf-8",
    )

    monkeypatch.setattr(
        "core.adapters.config.get_config",
        lambda: {"obsidian_vault_path": str(tmp_path)},
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_title_hit_outranks_body_hit(self, temp_vault):
        data = _collect_vault_search("checkout")
        titles = [r["title"] for r in data["results"]]
        # "Shopify checkout recovered" has the term in the title; the
        # other Wins note only has a single body mention.
        assert titles[0].lower().startswith("shopify-checkout")

    def test_irrelevant_notes_dropped(self, temp_vault):
        data = _collect_vault_search("checkout")
        paths = [r["path"] for r in data["results"]]
        assert not any("pattern.md" in p for p in paths)
        assert not any("pick-obsidian.md" in p for p in paths)

    def test_frontmatter_tag_is_searchable(self, temp_vault):
        data = _collect_vault_search("performance")
        assert any("vault-indexing.md" in r["path"] for r in data["results"])

    def test_snippet_windows_the_hit(self, temp_vault):
        data = _collect_vault_search("rate-limited")
        hit = next(r for r in data["results"] if "rate-limit.md" in r["path"])
        assert "rate-limited" in hit["snippet"].lower()

    def test_result_carries_expected_fields(self, temp_vault):
        r = _collect_vault_search("checkout")["results"][0]
        for key in ("path", "title", "folder", "mtime", "tags",
                    "score", "snippet"):
            assert key in r

    def test_score_strictly_positive_when_matched(self, temp_vault):
        data = _collect_vault_search("checkout")
        assert data["results"]
        assert all(r["score"] > 0 for r in data["results"])


# ---------------------------------------------------------------------------
# Folder filter
# ---------------------------------------------------------------------------


class TestFolderFilter:
    def test_narrow_to_wins(self, temp_vault):
        data = _collect_vault_search("checkout", type_filter="Wins")
        assert data["type"] == "Wins"
        assert data["results"]
        for r in data["results"]:
            assert r["path"].startswith("Wins/")

    def test_unknown_filter_falls_back_to_full_vault(self, temp_vault):
        data = _collect_vault_search("checkout", type_filter="Nonesuch")
        # Filter gets cleared rather than producing an empty list.
        assert data["type"] == ""
        assert data["results"]

    def test_empty_folder_returns_empty(self, temp_vault):
        # Templates exists in the folder map but we didn't seed any notes.
        (temp_vault / "Templates").mkdir()
        data = _collect_vault_search("checkout", type_filter="Templates")
        assert data["results"] == []


# ---------------------------------------------------------------------------
# Browse mode — empty query
# ---------------------------------------------------------------------------


class TestBrowseMode:
    def test_empty_query_returns_newest_first(self, temp_vault, monkeypatch):
        # Bump one file's mtime so we have a deterministic leader.
        target = temp_vault / "Wins" / "vault-indexing.md"
        new_mtime = target.stat().st_mtime + 5000
        import os
        os.utime(target, (new_mtime, new_mtime))

        data = _collect_vault_search("")
        assert data["results"]
        assert data["results"][0]["path"] == "Wins/vault-indexing.md"

    def test_empty_query_respects_limit(self, temp_vault):
        data = _collect_vault_search("", limit=2)
        assert len(data["results"]) == 2


# ---------------------------------------------------------------------------
# Resilience + envelope
# ---------------------------------------------------------------------------


class TestResilience:
    def test_missing_vault_raises_not_configured(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        from dashboard.app import _VaultNotConfigured
        with pytest.raises(_VaultNotConfigured):
            _collect_vault_search("x")

    def test_oversize_body_does_not_crash(self, temp_vault):
        big = temp_vault / "Wins" / "huge.md"
        big.write_text("needle\n" + ("x" * 300_000), encoding="utf-8")
        data = _collect_vault_search("needle")
        assert any("huge.md" in r["path"] for r in data["results"])

    def test_snippet_never_contains_newlines(self, temp_vault):
        data = _collect_vault_search("checkout")
        for r in data["results"]:
            assert "\n" not in r["snippet"]


# ---------------------------------------------------------------------------
# Endpoint — /api/vault/search
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    def test_returns_200_with_results(self, temp_vault):
        h = _handler("q=checkout")
        h._api_vault_search()
        status, data = h._captured[-1]
        assert status == 200
        assert data["configured"] is True
        assert data["results"]

    def test_empty_query_browse(self, temp_vault):
        h = _handler("q=")
        h._api_vault_search()
        status, data = h._captured[-1]
        assert status == 200
        assert data["results"]

    def test_type_param_flows_through(self, temp_vault):
        h = _handler("q=checkout&type=Wins")
        h._api_vault_search()
        status, data = h._captured[-1]
        assert status == 200
        assert data["type"] == "Wins"
        for r in data["results"]:
            assert r["path"].startswith("Wins/")

    def test_limit_param_clamped(self, temp_vault):
        h = _handler("q=&limit=1")
        h._api_vault_search()
        _, data = h._captured[-1]
        assert len(data["results"]) == 1

    def test_bad_limit_falls_back(self, temp_vault):
        h = _handler("q=&limit=not-a-number")
        h._api_vault_search()
        _, data = h._captured[-1]
        assert isinstance(data["results"], list)

    def test_missing_vault_returns_soft_envelope(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        h = _handler("q=x")
        h._api_vault_search()
        status, data = h._captured[-1]
        # Never a 500 — the UI always gets a parseable envelope.
        assert status == 200
        assert data["configured"] is False
        assert data["results"] == []
