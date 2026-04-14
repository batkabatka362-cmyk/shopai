"""Test-suite-wide fixtures.

The autouse fixtures here block real network egress from the
adapter layer. Without them, integration tests that run a full
autonomous cycle would call ``DDGSAdapter._http_get`` for real
(DDGS is the only search adapter "configured" without an API
key, so the SmartRouter picks it for every search), and the
20-minute slowdown observed pre-fix was the result.

The block is intentionally narrow:

  * ``DDGSAdapter._http_get`` returns an empty HTML body so
    parsing yields zero hits — the engine flow's "no results"
    branch fires cleanly.
  * Other adapters (Brave, Serper, every Shopify adapter,
    every LLM adapter) are NOT patched here because they all
    require API keys / tokens that the test environment never
    sets, so ``is_configured()`` already keeps them off the
    network.

Tests that explicitly want to verify DDGS HTML parsing patch
``_http_get`` themselves with their own canned HTML — those
local patches still work because pytest applies fixture
patches per-test, not globally.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _block_ddgs_network(monkeypatch):
    """Patch ``DDGSAdapter._http_get`` so it never makes a real
    HTTP call during the test suite.

    Returns an empty HTML body so the parser yields zero hits;
    the engine's "no results" branch handles the rest.

    Tests that need to assert DDGS parser behaviour patch
    ``_http_get`` again inside their own ``with patch.object(...)``
    block — those local patches override this autouse fixture
    for the duration of the test.
    """
    try:
        from core.adapters.search.ddgs import DDGSAdapter
    except Exception:
        return
    monkeypatch.setattr(
        DDGSAdapter,
        "_http_get",
        lambda self, url, headers=None: "",
    )


@pytest.fixture(autouse=True)
def _isolate_default_belief_store(tmp_path_factory, monkeypatch):
    """Wave 6 #5: keep the process-wide default BeliefStore out of
    the repo.

    Wave 6 #4 gave BeliefStore optional disk persistence, and Wave
    6 #5 wires the orchestrator's default advisor to a shared
    persistent singleton. Without this fixture, any test that
    runs a cycle with an executed action would write a real
    ``core/mentality/.state/beliefs.json`` file into the repo and
    leak posteriors into later tests.

    This fixture resets the singleton before each test and points
    the default path at a per-test tmp dir via env var, so every
    test starts with a fresh, isolated in-memory-and-tmp-only
    belief store.
    """
    try:
        from core.mentality import reset_default_belief_store
    except Exception:
        yield
        return
    reset_default_belief_store()
    tmp = tmp_path_factory.mktemp("beliefs")
    monkeypatch.setenv("SHOPAI_BELIEFS_PATH", str(tmp / "beliefs.json"))
    yield
    reset_default_belief_store()


@pytest.fixture(autouse=True)
def _isolate_default_idempotency_cache():
    """Option V: keep the process-wide idempotency cache from
    leaking results between tests.

    The router now consults ``get_idempotency_cache()`` before
    dispatching, and the default singleton ships with a TTL for
    ``CHAT_COMPLETE`` / ``EMBED_TEXT`` / ``WEB_SEARCH``. Without
    this fixture, a router test that calls CHAT_COMPLETE twice
    in the same process would hit the cache on the second call
    and skip its adapter entirely — causing flaky cross-test
    assertions about "which adapter was invoked".

    The fixture installs a **no-policy** cache as the singleton
    for the duration of each test: the router still consults it,
    it still records hit/miss/skipped counters, but nothing ever
    caches. Tests that explicitly cover caching behaviour can
    instantiate their own ``IdempotencyCache`` with populated
    policies and hand it to ``SmartRouter(idempotency_cache=...)``.
    """
    try:
        import core.adapters.idempotency as _idem
    except Exception:
        yield
        return
    _idem.reset_idempotency_cache()
    _idem._default_cache = _idem.IdempotencyCache(policies={})
    yield
    _idem.reset_idempotency_cache()


@pytest.fixture(autouse=True)
def _isolate_default_dead_letter_ledger():
    """Option Y: keep the router's default dead-letter ledger from
    writing test-run failures into the repo.

    The router singleton writes to ``core/adapters/.state/deadletter.jsonl``
    by default. Swapping in a fresh in-memory ledger for the
    duration of each test prevents cross-test leakage and avoids
    touching the filesystem entirely.
    """
    try:
        import core.adapters.deadletter as _dl
    except Exception:
        yield
        return
    _dl.reset_dead_letter_ledger()
    _dl._default_ledger = _dl.DeadLetterLedger(path=None)
    yield
    _dl.reset_dead_letter_ledger()


@pytest.fixture(autouse=True)
def _isolate_default_cost_ledger():
    """Option Z: keep the process-wide cost ledger from leaking
    attribution rows between tests.

    The router records every realised cost against
    ``get_cost_ledger()`` by default, tagged with the caller. Tests
    that don't care about cost attribution still end up sharing
    rows through the singleton — this fixture swaps in a fresh
    ledger for every test so counts and per-caller rollups start
    at zero.
    """
    try:
        import core.adapters.cost_ledger as _cl
    except Exception:
        yield
        return
    _cl.reset_cost_ledger()
    yield
    _cl.reset_cost_ledger()


@pytest.fixture(autouse=True)
def _isolate_reliability_state():
    """Option E: reset the autonomous reliability collector's
    cross-cycle delta baseline between tests.

    ``collect_reliability_signal()`` accumulates dead-letter and
    cost totals across calls so each cycle can see "what happened
    since my last look". Tests that assert exact delta values
    would otherwise inherit the previous test's baseline and
    flake — this fixture zeroes the state before every test.
    """
    try:
        from core.autonomous.reliability import reset_reliability_state
    except Exception:
        yield
        return
    reset_reliability_state()
    yield
    reset_reliability_state()


@pytest.fixture(autouse=True)
def _isolate_default_reflection_synth(tmp_path_factory, monkeypatch):
    """Wave 6 #6: keep the process-wide default ReflectionSynthesizer
    out of the repo.

    Wave 6 #6 made the synthesizer persist promoted patterns to a
    JSONL ledger and added a process-wide default. Without this
    fixture, any test that runs a cycle with a reflection-promoted
    pattern would write a real ``core/reflection/.state/reflection_ledger.jsonl``
    file into the repo and leak state into later tests.

    Resets the singleton before and after each test, and points
    the default path at a per-test tmp dir via env var.
    """
    try:
        from core.reflection.synthesizer import reset_default_synthesizer
    except Exception:
        yield
        return
    reset_default_synthesizer()
    tmp = tmp_path_factory.mktemp("reflection")
    monkeypatch.setenv(
        "SHOPAI_REFLECTION_PATH", str(tmp / "reflection_ledger.jsonl"),
    )
    yield
    reset_default_synthesizer()
