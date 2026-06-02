"""Persistent operator-set overrides for cycle thresholds.

Lets operators (or env-gated auto-relax bridge) adjust the
reliability threshold + min sample size at runtime without
restarting the process or editing env vars. The lookup
priority is:

  1. This overrides file (operator-set, writable)
  2. Environment variable (operator config at startup)
  3. Module default

Why a file rather than just env: env-gated decisions get
made once at process boot. The autonomous loop runs as a
long-lived cron job; if low_advance_rate has been firing
for 3 days, the operator wants to nudge the threshold
TODAY, not wait for a restart.

Public surface
--------------
- ``load_overrides()`` -> dict.
- ``set_override(key, value)`` -> bool.
- ``clear_override(key)`` -> bool.
- ``clear_all()``.
- ``resolve_threshold()``, ``resolve_min_sample()`` --
  layered lookup helpers used by the controller.

Pattern J test guard: writes short-circuit under pytest;
reads still work (callers can mock the file path with
``_reset_for_tests``).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading

# W962-42: span load+modify+save so concurrent set/clear
# don't lose updates.
_LOCK = threading.RLock()
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_OVERRIDES_PATH = Path(
    os.environ.get(
        "SHOPAI_CYCLE_OVERRIDES_PATH",
        "data/cycle_overrides.json",
    )
)

# Known keys with their typed defaults. The override file
# is unbounded, but only these keys are consulted by the
# resolver helpers below.
_KEYS_FLOAT = {
    "auto_execute_threshold": 0.9,
}
_KEYS_INT = {
    "auto_execute_min_sample": 5,
}


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _OVERRIDES_PATH.exists():
            return {}
        with _OVERRIDES_PATH.open(
            "r", encoding="utf-8",
        ) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "cycle_overrides: load failed (%s)", exc,
        )
        return {}


def _atomic_write(data: dict[str, Any]) -> None:
    try:
        _OVERRIDES_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "cycle_overrides: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cycle_overrides_",
            suffix=".json",
            dir=str(_OVERRIDES_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(temp_path_str, _OVERRIDES_PATH)
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError as cleanup_exc:
                logger.debug(
                    "temp cleanup failed: %s", cleanup_exc,
                )
            raise
    except OSError as exc:
        logger.debug(
            "cycle_overrides: write failed (%s)", exc,
        )


def load_overrides() -> dict[str, Any]:
    """Return the current override dict. Always safe to call."""
    return _load_raw()


def set_override(key: str, value: Any) -> bool:
    """Set ``key`` to ``value`` in the override file.

    Pattern J short-circuits under pytest. Returns True on
    write, False on test-env / I/O error / unknown key.
    """
    if _is_test_environment():
        return False
    if not isinstance(key, str) or not key:
        return False
    if key not in _KEYS_FLOAT and key not in _KEYS_INT:
        # Refuse unknown keys so a typo doesn't silently
        # write something the resolver won't read.
        logger.debug(
            "cycle_overrides: unknown key %r", key,
        )
        return False
    if key in _KEYS_FLOAT:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
    if key in _KEYS_INT:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return False
    # W962-42: serialise the read+update+write.
    with _LOCK:
        data = _load_raw()
        data[key] = value
        _atomic_write(data)
    return True


def clear_override(key: str) -> bool:
    """Remove ``key`` from the override file. Returns True
    when a key was removed."""
    if _is_test_environment():
        return False
    # W962-42: serialise the read+modify+write.
    with _LOCK:
        data = _load_raw()
        if key not in data:
            return False
        del data[key]
        _atomic_write(data)
    return True


def clear_all() -> None:
    """Operator escape hatch: wipe the overrides file."""
    if _is_test_environment():
        return
    if _OVERRIDES_PATH.exists():
        try:
            _OVERRIDES_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "cycle_overrides: unlink raised: %s", exc,
            )


def _resolve(
    key: str,
    env_var: str,
    default: Any,
    coerce,
) -> Any:
    """Layered resolution: overrides file > env > default."""
    data = _load_raw()
    if key in data:
        try:
            return coerce(data[key])
        except (TypeError, ValueError) as exc:
            logger.debug(
                "cycle_overrides: %s coerce failed (%s)",
                key, exc,
            )
    raw = os.environ.get(env_var)
    if raw is not None:
        try:
            return coerce(raw)
        except (TypeError, ValueError) as exc:
            logger.debug(
                "cycle_overrides: %s env coerce failed (%s)",
                env_var, exc,
            )
    return default


def resolve_threshold() -> float:
    """Get the effective auto-execute threshold.
    Override file > SHOPAI_AUTO_EXECUTE_THRESHOLD env > 0.9.
    """
    return _resolve(
        "auto_execute_threshold",
        "SHOPAI_AUTO_EXECUTE_THRESHOLD",
        _KEYS_FLOAT["auto_execute_threshold"],
        float,
    )


def resolve_min_sample() -> int:
    """Get the effective min-sample size.
    Override file > SHOPAI_AUTO_EXECUTE_MIN_SAMPLE env > 5.
    """
    return _resolve(
        "auto_execute_min_sample",
        "SHOPAI_AUTO_EXECUTE_MIN_SAMPLE",
        _KEYS_INT["auto_execute_min_sample"],
        int,
    )


def _reset_for_tests(path: Path | None = None) -> None:
    global _OVERRIDES_PATH
    if path is not None:
        _OVERRIDES_PATH = path
