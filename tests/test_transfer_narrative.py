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
    TransferRecord,
    format_narrative,
    is_transfer_narrative,
    parse_engine_action,
    parse_source_run_count,
    parse_source_store,
    parse_target_store,
    record_from_narrative,
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
        # Round-trip the source_run_count too.
        assert parse_source_run_count(n) == 5


# ─── parse_source_run_count ──────────────────────────────────


class TestParseSourceRunCount:

    def test_canonical_form_single_digit(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=3,
        )
        assert parse_source_run_count(n) == 3

    def test_canonical_form_multi_digit(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=147,
        )
        assert parse_source_run_count(n) == 147

    def test_zero_run_count(self):
        """``0 prior successful run(s)`` is a valid value -- when
        a transfer is applied against a source with no prior
        successful executions yet (edge case)."""
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=0,
        )
        assert parse_source_run_count(n) == 0

    def test_operator_prefix_form(self):
        n = format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=4,
            operator_note="parity push",
        )
        assert parse_source_run_count(n) == 4

    def test_malformed_returns_none(self):
        # Not a transfer narrative at all.
        assert parse_source_run_count("") is None
        assert parse_source_run_count("random text") is None
        # Marker present but no "Source had N" phrase.
        assert (
            parse_source_run_count(
                "Transfer suggestion: loyalty/x from a to b."
            )
            is None
        )

    def test_phrase_present_no_digits_returns_none(self):
        """If the phrase 'Source had ' appears but isn't followed
        by digits, return None rather than guessing."""
        bad = (
            "Transfer suggestion: loyalty/x from a to b. "
            "Source had several prior successful run(s)."
        )
        assert parse_source_run_count(bad) is None

    def test_non_transfer_marker_returns_none(self):
        """The phrase 'Source had ' shouldn't be parsed in
        narratives that aren't transfer narratives -- avoid
        false-positive parses on unrelated text."""
        bad = "Source had 5 prior successful runs (not a transfer)."
        assert parse_source_run_count(bad) is None


# ─── TransferRecord + record_from_narrative ──────────────────


class TestRecordFromNarrative:

    def test_canonical_narrative_returns_full_record(self):
        n = format_narrative(
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-alpha",
            to_store="store-beta",
            source_run_count=3,
        )
        rec = record_from_narrative(n)
        assert rec is not None
        assert isinstance(rec, TransferRecord)
        assert rec.narrative == n
        assert rec.engine == "loyalty"
        assert rec.action_type == "mint_loyalty_code"
        assert rec.from_store == "store-alpha"
        assert rec.to_store == "store-beta"
        assert rec.source_run_count == 3

    def test_operator_prefix_returns_full_record(self):
        n = format_narrative(
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            from_store="x", to_store="y",
            source_run_count=7,
            operator_note="parity push",
        )
        rec = record_from_narrative(n)
        assert rec is not None
        assert rec.engine == "cart_recovery"
        assert rec.from_store == "x"
        assert rec.to_store == "y"
        assert rec.source_run_count == 7

    def test_non_transfer_returns_none(self):
        """Anything without the marker isn't a transfer record."""
        assert record_from_narrative("") is None
        assert record_from_narrative("just some narrative") is None
        # Empty body but contains the literal marker text -- still
        # surface as a record (with degraded fields). The
        # is-transfer-or-not boundary lives at the marker check.
        rec = record_from_narrative("Transfer suggestion:")
        assert rec is not None
        assert rec.engine == ""
        assert rec.from_store == ""

    def test_partial_narrative_returns_partial_record(self):
        """Narrative with the marker but a malformed tail
        returns a record with empty / None fields -- matches
        the permissive contract of the individual parsers."""
        bad = (
            "Transfer suggestion: loyalty/mint_loyalty_code "
            "from alpha to beta."
        )  # missing "Source had N..." tail
        rec = record_from_narrative(bad)
        assert rec is not None
        assert rec.engine == "loyalty"
        assert rec.action_type == "mint_loyalty_code"
        assert rec.from_store == "alpha"
        assert rec.to_store == "beta"
        # Run count was missing → None.
        assert rec.source_run_count is None

    def test_record_is_frozen(self):
        rec = record_from_narrative(format_narrative(
            engine="loyalty", action_type="x",
            from_store="a", to_store="b",
            source_run_count=1,
        ))
        with pytest.raises(Exception):
            rec.engine = "modified"  # type: ignore[misc]
