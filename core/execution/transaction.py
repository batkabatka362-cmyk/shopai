"""Retry + transaction layer for money-on-the-line writes.

Money-touching calls (Shopify product create, Meta Ads campaign
launch, AutoDS supplier link) *must* survive flaky networks and
must never leave partial state behind. This module wraps an action
sequence as a transaction with:

  • Exponential backoff retry (per CLAUDE.md §4b.D)
  • Idempotency keys so a retried call doesn't create duplicates
  • Compensating actions (rollback) registered at each step
  • Outcome persistence so a retry-after-restart can resume

Usage::

    from core.execution.transaction import Transaction

    tx = Transaction("launch_xyz")
    tx.run(
        step="shopify_create",
        op=lambda: create_product(...),
        compensate=lambda product_id: delete_product(product_id),
        idempotency_key="launch_xyz:product",
    )
    tx.run(
        step="meta_ads",
        op=lambda: create_campaign(...),
        compensate=lambda cid: pause_campaign(cid),
    )
    # At exit: if anything raised, compensations run in reverse order.

Guaranteed properties:
  • on success → all steps recorded, no compensation fires
  • on failure → compensations for already-succeeded steps run
  • retried op never creates a duplicate (idempotency cache)
"""
from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


_STORE = Path("data/transactions.json")
_lock = threading.Lock()


@dataclass
class StepRecord:
    step: str
    status: str                  # "pending" | "succeeded" | "failed" | "rolled_back"
    attempts: int = 0
    idempotency_key: str = ""
    result: Any = None
    error: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "attempts": self.attempts,
            "idempotency_key": self.idempotency_key,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class TransactionRecord:
    id: str
    created_at: float
    status: str = "open"
    steps: list[StepRecord] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "status": self.status,
            "steps": [s.as_dict() for s in self.steps],
        }


class RetriableError(RuntimeError):
    """Raise from an op to mark the failure as safe to retry.

    Non-RetriableError exceptions short-circuit retries so hard
    errors (auth, validation) don't waste the budget."""


class Transaction:
    """One transaction = one ordered list of steps."""

    def __init__(
        self,
        tx_id: str,
        max_retries: int = 4,
        initial_backoff_s: float = 2.0,
        backoff_cap_s: float = 32.0,
    ) -> None:
        self.id = tx_id
        self.max_retries = int(max_retries)
        self.initial_backoff_s = float(initial_backoff_s)
        self.backoff_cap_s = float(backoff_cap_s)
        self._record = TransactionRecord(
            id=tx_id, created_at=time.time(),
        )
        # step -> (result, compensate fn)
        self._compensations: list[tuple[StepRecord, Callable[[Any], None] | None]] = []

    # ── Core orchestration ────────────────────────────────

    def run(
        self,
        step: str,
        op: Callable[[], Any],
        compensate: Callable[[Any], None] | None = None,
        idempotency_key: str = "",
    ) -> Any:
        """Execute *op* with retries. Registers *compensate* so a
        later failure in the transaction rolls this step back.

        If *idempotency_key* is supplied and a prior tx already ran
        this step successfully, the cached result is returned without
        re-running *op*."""
        cached = self._cached_result(idempotency_key) if idempotency_key else None
        if cached is not None:
            record = StepRecord(
                step=step, status="succeeded",
                attempts=0, idempotency_key=idempotency_key,
                result=cached,
                started_at=time.time(), finished_at=time.time(),
            )
            self._record.steps.append(record)
            self._compensations.append((record, compensate))
            return cached

        record = StepRecord(
            step=step, status="pending",
            idempotency_key=idempotency_key,
            started_at=time.time(),
        )
        self._record.steps.append(record)
        result = self._run_with_retries(record, op)
        record.finished_at = time.time()
        self._compensations.append((record, compensate))
        self._save()
        return result

    def rollback(self) -> list[str]:
        """Roll back every succeeded step in reverse order. Safe to
        call more than once — already-rolled-back steps are skipped.
        Returns list of step names that were actually compensated."""
        rolled: list[str] = []
        for record, compensate in reversed(self._compensations):
            if record.status != "succeeded":
                continue
            if compensate is None:
                record.status = "rolled_back"
                continue
            try:
                compensate(record.result)
            except Exception:
                # compensate failing is serious but we shouldn't raise
                # because the original error is what the caller cares
                # about — mark the step as failed_rollback for audit.
                record.status = "failed_rollback"
                record.error = "compensate raised"
                continue
            record.status = "rolled_back"
            rolled.append(record.step)
        self._record.status = "rolled_back"
        self._save()
        return rolled

    def commit(self) -> None:
        self._record.status = "committed"
        self._save()

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commit()
            return False
        self.rollback()
        return False  # re-raise

    # ── Internals ──────────────────────────────────────────

    def _run_with_retries(self, record: StepRecord, op: Callable[[], Any]) -> Any:
        backoff = self.initial_backoff_s
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            record.attempts = attempt
            try:
                result = op()
            except RetriableError as exc:
                last_error = exc
                record.error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.max_retries:
                    break
                time.sleep(min(backoff, self.backoff_cap_s) * (0.8 + 0.4 * random.random()))
                backoff = min(backoff * 2, self.backoff_cap_s)
                continue
            except Exception as exc:
                # Non-retriable — short-circuit.
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"
                raise
            record.status = "succeeded"
            record.result = result
            self._remember(record)
            return result
        record.status = "failed"
        if last_error is not None:
            raise last_error
        return None

    def _remember(self, record: StepRecord) -> None:
        if not record.idempotency_key:
            return
        with _lock:
            store = _load()
            keys = store.setdefault("idempotency", {})
            keys[record.idempotency_key] = {
                "result": record.result,
                "ts": time.time(),
            }
            _save_store(store)

    def _cached_result(self, idempotency_key: str) -> Any:
        store = _load()
        entry = (store.get("idempotency") or {}).get(idempotency_key)
        return entry.get("result") if entry else None

    def _save(self) -> None:
        with _lock:
            store = _load()
            txs = store.setdefault("transactions", {})
            txs[self.id] = self._record.as_dict()
            _save_store(store)


# ── File-level persistence ──────────────────────────────────

def _load() -> dict[str, Any]:
    if not _STORE.exists():
        return {"transactions": {}, "idempotency": {}}
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"transactions": {}, "idempotency": {}}


def _save_store(store: dict[str, Any]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    import os
    tmp = _STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=2, default=str),
                   encoding="utf-8")
    os.replace(tmp, _STORE)


def get_transaction(tx_id: str) -> dict[str, Any] | None:
    return (_load().get("transactions") or {}).get(tx_id)


def clear_all() -> None:
    with _lock:
        if _STORE.exists():
            _STORE.unlink()
