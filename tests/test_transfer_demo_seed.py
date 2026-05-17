"""Tests for the realism-mode logic in
``scripts/transfer_demo_seed.py``.

The seed script is normally invoked end-to-end against a real
SQLite-backed approval queue (it's deliberately not wired as
a CLI subcommand — see PR #246's module docstring for why).
These tests target the small pure helper that decides each
row's outcome polarity / revenue / skip, since that's where
``--realism`` actually changes behaviour.
"""
from __future__ import annotations

import importlib.util


def _load_seed_module():
    """Load the script as a regular Python module despite its
    top-level path-mangling for direct ``python scripts/...``
    invocation."""
    spec = importlib.util.spec_from_file_location(
        "transfer_demo_seed",
        "scripts/transfer_demo_seed.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── default (happy-path) ────────────────────────────────────


class TestHappyPathOutcome:

    def test_every_row_gets_positive(self):
        mod = _load_seed_module()
        # Default behaviour: realism=False → every row is positive.
        for i in range(20):
            outcome = mod._outcome_for(i, realism=False)
            assert outcome is not None
            polarity, revenue = outcome
            assert polarity == "positive"
            assert revenue > 0

    def test_revenue_monotonic_with_i(self):
        """Happy-path revenue is ``50 * (i + 1)`` — grows with i
        so multiple seeded rows have distinct values."""
        mod = _load_seed_module()
        assert mod._outcome_for(0, realism=False) == ("positive", 50.0)
        assert mod._outcome_for(1, realism=False) == ("positive", 100.0)
        assert mod._outcome_for(4, realism=False) == ("positive", 250.0)


# ─── --realism ───────────────────────────────────────────────


class TestRealismMode:

    def test_distribution_over_full_cycle(self):
        """Realistic mode cycles every 5 rows:
          i % 5 == 0 → no outcome (None)
          i % 5 == 1 → negative
          else       → positive
        Verify the 5-row block has the exact expected shape."""
        mod = _load_seed_module()
        outcomes = [mod._outcome_for(i, realism=True) for i in range(5)]
        # Slot 0: no outcome
        assert outcomes[0] is None
        # Slot 1: negative
        assert outcomes[1] is not None
        assert outcomes[1][0] == "negative"
        assert outcomes[1][1] < 0
        # Slots 2-4: positive
        for slot in (2, 3, 4):
            assert outcomes[slot] is not None
            assert outcomes[slot][0] == "positive"
            assert outcomes[slot][1] > 0

    def test_cycle_repeats(self):
        """Slot 5 should look like slot 0 (cycle repeats)."""
        mod = _load_seed_module()
        assert (
            mod._outcome_for(5, realism=True)
            is None
        )
        assert mod._outcome_for(6, realism=True)[0] == "negative"
        assert mod._outcome_for(7, realism=True)[0] == "positive"

    def test_distribution_over_25_rows(self):
        """Across a 25-row sample (5 full cycles), the
        distribution should be 5 / 5 / 15 (none/neg/pos)."""
        mod = _load_seed_module()
        none_count = neg_count = pos_count = 0
        for i in range(25):
            out = mod._outcome_for(i, realism=True)
            if out is None:
                none_count += 1
            elif out[0] == "negative":
                neg_count += 1
            elif out[0] == "positive":
                pos_count += 1
        assert none_count == 5
        assert neg_count == 5
        assert pos_count == 15


# ─── parity: realism=False matches old behaviour ─────────────


class TestBackwardCompat:

    def test_realism_false_matches_pre_flag_behaviour(self):
        """The script used to always seed positive outcomes
        with revenue=50*(i+1). The default branch of
        ``_outcome_for`` MUST preserve that exact output --
        otherwise any operator relying on the old seed gets
        silent behaviour drift."""
        mod = _load_seed_module()
        for i in range(10):
            assert (
                mod._outcome_for(i, realism=False)
                == ("positive", 50.0 * (i + 1))
            )
