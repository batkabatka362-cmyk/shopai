"""Tests for the persist_path runtime guards added in place
of bare ``assert`` statements.

Before: ``assert self._persist_path is not None`` would be
stripped by ``python -O``, leaving a confusing
``AttributeError: 'NoneType' object has no attribute 'parent'``
downstream when persist_path was None.

After: an explicit ``raise RuntimeError(...)`` fires with a
clear message regardless of -O mode.
"""
from __future__ import annotations

import pytest


class TestSynthesizerGuard:

    def test_append_to_ledger_raises_when_path_none(self):
        from core.reflection.synthesizer import ReflectionSynthesizer
        # Construct without a persist path
        synth = ReflectionSynthesizer(persist_path=None)
        # Build a minimal fake pattern that _append_to_ledger
        # would accept structurally; the runtime guard fires
        # before any field access happens.

        class _FakePattern:
            signature = "x"
            kind = "y"
            sample_text = "z"
            occurrences = 1
            first_seen = 0.0
            last_seen = 0.0
            confidence = 0.5

        with pytest.raises(RuntimeError, match="persist_path not configured"):
            synth._append_to_ledger(_FakePattern())

    def test_rewrite_ledger_locked_raises_when_path_none(self):
        from core.reflection.synthesizer import ReflectionSynthesizer
        synth = ReflectionSynthesizer(persist_path=None)
        with pytest.raises(RuntimeError, match="persist_path not configured"):
            synth._rewrite_ledger_locked()

    def test_rehydrate_from_disk_raises_when_path_none(self):
        from core.reflection.synthesizer import ReflectionSynthesizer
        synth = ReflectionSynthesizer(persist_path=None)
        with pytest.raises(RuntimeError, match="persist_path not configured"):
            synth._rehydrate_from_disk()


class TestValuesGuard:

    def test_save_to_disk_raises_when_path_none(self):
        from core.mentality.values import BeliefStore
        store = BeliefStore(persist_path=None)
        with pytest.raises(RuntimeError, match="persist_path not configured"):
            store._save_to_disk_locked()

    def test_load_from_disk_raises_when_path_none(self):
        from core.mentality.values import BeliefStore
        store = BeliefStore(persist_path=None)
        with pytest.raises(RuntimeError, match="persist_path not configured"):
            store._load_from_disk()
