"""Tests for ``core.transfer_narrative`` — the single source of
truth for transfer-apply narrative format + parsing.

Each parser is exercised against both the canonical format and
the operator-prefixed variant, plus malformed inputs (should
degrade gracefully to empty strings, not raise).
"""
from __future__ import annotations

import pytest

from core.transfer_narrative import (
    SQL_LIKE_CLAUSE,
    format_narrative,
    is_transfer_narrative,
    parse_engine_action,
    parse_source_store,
    parse_target_store,
)


# ─── format_narrative ────────────────────────────────────────


class TestFormat:

    def test_canonical_format(self):
        n = format_narrative(
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-a",
            to_store="store-b",
            source_run_count=3,
        )
        assert (
            n
            == "Transfer suggestion: loyalty/mint_loyalty_code "
               "from store-a to store-b. "
               "Source had 3 prior successful run(s)."
        )

    def test_operator_note_prepended(self):
        n = format_narrative(
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-a",
            to_store="store-b",
            source_run_count=1,
            operator_note="black friday parity",
        )
        assert n.startswith("black friday parity  ||  ")
        assert "Transfer suggestion:" in n
        assert "Source had 1 prior successful run(s)." in n

    def test_empty_operator_note_no_prefix(self):
        """An empty operator_note string should NOT inject a
        separator — same output as omitting it."""
        n_empty = format_narrative(
            engine="x", action_type="y",
            from_store="a", to_store="b",
            source_run_count=2,
            operator_note="",
        )
        n_omit = format_narrative(
            engine="x", action_type="y",
            from_store="a", to_store="b",
            source_run_count=2,
        )
        assert n_empty == n_omit
        assert "||" not in n_empty


# ─── is_transfer_narrative ───────────────────────────────────


class TestIsTransferNarrative:

    def test_canonical_form_recognised(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=1,
        )
        assert is_transfer_narrative(n) is True

    def test_operator_prefix_form_recognised(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=1,
            operator_note="my note",
        )
        assert is_transfer_narrative(n) is True

    def test_unrelated_narrative_rejected(self):
        assert is_transfer_narrative("") is False
        assert is_transfer_narrative("just some narrative") is False
        assert (
            is_transfer_narrative("Transfer suggested but missing the marker")
            is False
        )


# ─── parse_source_store ──────────────────────────────────────


class TestParseSourceStore:

    def test_canonical_form(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="alpha", to_store="beta",
            source_run_count=1,
        )
        assert parse_source_store(n) == "alpha"

    def test_operator_prefix_form(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="alpha", to_store="beta",
            source_run_count=1,
            operator_note="some note",
        )
        assert parse_source_store(n) == "alpha"

    def test_malformed_returns_empty(self):
        assert parse_source_store("") == ""
        assert parse_source_store("random text") == ""
        # Marker present but no "from <A> to <B>"
        assert (
            parse_source_store("Transfer suggestion: loyalty/x. malformed end.")
            == ""
        )


# ─── parse_target_store ──────────────────────────────────────


class TestParseTargetStore:

    def test_canonical_form(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="alpha", to_store="beta",
            source_run_count=1,
        )
        assert parse_target_store(n) == "beta"

    def test_operator_prefix_form(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="alpha", to_store="beta",
            source_run_count=1,
            operator_note="some note",
        )
        assert parse_target_store(n) == "beta"

    def test_malformed_returns_empty(self):
        assert parse_target_store("") == ""
        assert parse_target_store("random text") == ""


# ─── parse_engine_action ─────────────────────────────────────


class TestParseEngineAction:

    def test_canonical_form(self):
        n = format_narrative(
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="a", to_store="b",
            source_run_count=1,
        )
        assert parse_engine_action(n) == (
            "loyalty", "mint_loyalty_code",
        )

    def test_operator_prefix_form(self):
        n = format_narrative(
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            from_store="a", to_store="b",
            source_run_count=1,
            operator_note="ops note",
        )
        assert parse_engine_action(n) == (
            "cart_recovery", "mint_cart_recovery_code",
        )

    def test_malformed_returns_empty_tuple(self):
        assert parse_engine_action("") == ("", "")
        assert parse_engine_action("random text") == ("", "")
        # Marker present but no slash in the engine/action pair
        assert (
            parse_engine_action("Transfer suggestion: invalidpair from a to b.")
            == ("", "")
        )


# ─── SQL_LIKE_CLAUSE ─────────────────────────────────────────


class TestSqlClause:

    def test_clause_is_string(self):
        """The clause is a parameter-free SQL fragment ready to
        drop into a WHERE."""
        assert isinstance(SQL_LIKE_CLAUSE, str)
        assert "narrative LIKE" in SQL_LIKE_CLAUSE

    def test_clause_matches_both_forms_via_sqlite(self):
        """Sanity check: run the LIKE clause against an
        in-memory SQLite DB to verify it actually matches both
        narrative formats."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, narrative TEXT)",
        )
        canon = format_narrative(
            engine="e", action_type="a",
            from_store="x", to_store="y",
            source_run_count=1,
        )
        prefixed = format_narrative(
            engine="e", action_type="a",
            from_store="x", to_store="y",
            source_run_count=1,
            operator_note="note",
        )
        unrelated = "not a transfer at all"
        for n in (canon, prefixed, unrelated):
            conn.execute("INSERT INTO t (narrative) VALUES (?)", (n,))

        rows = conn.execute(
            f"SELECT narrative FROM t WHERE {SQL_LIKE_CLAUSE}",
        ).fetchall()
        narratives = {r[0] for r in rows}
        assert canon in narratives
        assert prefixed in narratives
        assert unrelated not in narratives


# ─── Round-trip ──────────────────────────────────────────────


class TestRoundTrip:

    def test_format_then_parse(self):
        """format_narrative → parse_* should round-trip cleanly."""
        n = format_narrative(
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-alpha",
            to_store="store-beta",
            source_run_count=5,
        )
        assert parse_source_store(n) == "store-alpha"
        assert parse_target_store(n) == "store-beta"
        assert parse_engine_action(n) == (
            "loyalty", "mint_loyalty_code",
        )
        assert is_transfer_narrative(n) is True
