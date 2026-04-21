"""Tiny pidfile helper — shared by the 24/7 daemons so the CLI
can tell whether one is running + how long it's been up.

Not a full-featured pidlock — no race-free locking, no stale
detection via /proc. Daemons write on start, delete on clean
exit; the CLI reader checks that the pid is in ``os.kill(pid,
0)`` alive. Good enough for owner-facing ``shopai autopilot-
status`` without pulling in heavy deps.

Pure stdlib. Thread-safe via a module-level lock during write
+ delete.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DEFAULT_DIR = Path("data")
_LOCK = threading.Lock()


@dataclass
class PidStatus:
    name: str
    running: bool
    pid: int = 0
    started_at: float = 0.0
    uptime_s: float = 0.0
    path: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "running": self.running,
            "pid": self.pid,
            "started_at": self.started_at,
            "uptime_s": round(self.uptime_s, 2),
            "path": self.path,
            "detail": self.detail,
        }


def _path_for(name: str, base: Path | None = None) -> Path:
    base = base or _DEFAULT_DIR
    safe = "".join(
        c for c in name
        if c.isalnum() or c in ("-", "_")
    ) or "daemon"
    return base / f"shopai-{safe}.pid"


def write(
    name: str, *, base: Path | None = None,
) -> Path:
    """Write the current PID + start timestamp into the pidfile.
    File format: two lines — ``<pid>\\n<unix_ts>\\n``. Idempotent;
    overwrites any existing file."""
    path = _path_for(name, base=base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        path.write_text(
            f"{os.getpid()}\n{time.time()}\n",
        )
    return path


def clear(
    name: str, *, base: Path | None = None,
) -> bool:
    """Remove the pidfile on clean shutdown. Returns True if
    a file was removed."""
    path = _path_for(name, base=base)
    with _LOCK:
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError:
                return False
    return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by another user —
        # treat as alive for the purposes of status.
        return True
    except OSError:
        return False
    return True


def read_status(
    name: str,
    *,
    base: Path | None = None,
    now_fn: Any = None,
) -> PidStatus:
    """Return a PidStatus for the daemon. If the pidfile
    is missing, PID is dead, or file is corrupt, running=False."""
    path = _path_for(name, base=base)
    now = float((now_fn or time.time)())
    if not path.exists():
        return PidStatus(
            name=name,
            running=False,
            path=str(path),
            detail="pidfile not found",
        )
    try:
        raw = path.read_text().strip().splitlines()
    except OSError as exc:
        return PidStatus(
            name=name,
            running=False,
            path=str(path),
            detail=f"read error: {exc}",
        )
    if not raw:
        return PidStatus(
            name=name,
            running=False,
            path=str(path),
            detail="empty pidfile",
        )
    try:
        pid = int(raw[0].strip())
    except ValueError:
        return PidStatus(
            name=name,
            running=False,
            path=str(path),
            detail="bad pid in file",
        )
    try:
        started = float(
            raw[1].strip(),
        ) if len(raw) > 1 else 0.0
    except ValueError:
        started = 0.0
    alive = _pid_alive(pid)
    return PidStatus(
        name=name,
        running=alive,
        pid=pid,
        started_at=started,
        uptime_s=max(0.0, now - started) if started else 0.0,
        path=str(path),
        detail="" if alive else (
            "pid not running (stale pidfile)"
        ),
    )


@contextlib.contextmanager
def lifecycle(
    name: str, *, base: Path | None = None,
):
    """Context manager: write on enter, clear on exit.
    Safe for signal-handler-based shutdowns — the ``with``
    block's finally always runs on normal exit; callers that
    exit via ``os._exit`` should call ``clear(name)``
    themselves."""
    path = write(name, base=base)
    try:
        yield path
    finally:
        clear(name, base=base)
