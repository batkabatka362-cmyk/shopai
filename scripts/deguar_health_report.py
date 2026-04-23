"""One-command Monday health report for Deguar.

Runs every audit script in sequence, captures their stdout +
exit code, and produces a single markdown report. Designed to
be cron-friendly:

    0 8 * * 1  cd ~/shopai && PYTHONPATH=. python \\
        scripts/deguar_health_report.py >> reports/cron.log

Output:
    reports/<YYYY-MM-DD>-health.md  — owner-readable summary
    stdout                           — same content + ANSI-free

Aggregates these 6 audits + 1 doctor probe:

    * doctor (cli.py)            — config + adapter health
    * scope_audit                 — Shopify OAuth scopes
    * collection_check            — smart collections populated
    * webhook_check               — order learning loop wired
    * tracking_check              — Meta/TikTok/GA pixels firing
    * checkout_check              — payment + shipping + URL gate
    * live_audit                  — images, dupes, pricing

Verdict:
    READY     — every audit returned 0
    WARNINGS  — some returned 1 (warning-only)
    BLOCKED   — at least one returned 2+ (blocker)

Each section in the report is collapsed by default so the
verdict + headline numbers are visible at a glance.

Read-only — calls each script's read-only audit, never writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AuditResult:
    name: str
    purpose: str
    rc: int = -1
    output: str = ""
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        if self.rc == 0:
            return "ok"
        if self.rc == 1:
            return "warning"
        if self.rc >= 2:
            return "blocked"
        return "error"

    @property
    def emoji(self) -> str:
        return {
            "ok": "✓", "warning": "⚠", "blocked": "✗",
            "error": "✗", "skipped": "·",
        }[self.status]


@dataclass
class HealthReport:
    generated_at: str
    store: str
    audits: list[AuditResult] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        statuses = {a.status for a in self.audits if not a.skipped}
        if "blocked" in statuses or "error" in statuses:
            return "BLOCKED"
        if "warning" in statuses:
            return "WARNINGS"
        if "ok" in statuses:
            return "READY"
        return "UNKNOWN"

    def counts(self) -> dict[str, int]:
        out = {"ok": 0, "warning": 0, "blocked": 0,
               "error": 0, "skipped": 0}
        for a in self.audits:
            out[a.status] = out.get(a.status, 0) + 1
        return out


# ── Runners ──────────────────────────────────────────────


def _run_audit(
    name: str, purpose: str,
    main_fn: Callable[[list[str] | None], int],
    argv: list[str] | None = None,
) -> AuditResult:
    """Call ``main_fn(argv)`` capturing stdout + exit code.
    Exceptions become ``error`` status with the traceback in
    ``output`` so the report doesn't lose the diagnostic."""
    buf = io.StringIO()
    res = AuditResult(name=name, purpose=purpose)
    try:
        with redirect_stdout(buf):
            rc = main_fn(argv or [])
        res.rc = int(rc) if rc is not None else 0
        res.output = buf.getvalue()
    except SystemExit as exc:
        # main() may sys.exit() instead of returning; capture
        # the code
        try:
            res.rc = int(exc.code) if exc.code is not None else 0
        except (TypeError, ValueError):
            res.rc = 2
        res.output = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        res.rc = -1
        res.output = buf.getvalue()
        res.error = (
            f"{type(exc).__name__}: {exc}\n"
            + traceback.format_exc()
        )
    return res


def _run_doctor() -> AuditResult:
    """The CLI doctor probe is the one audit not under
    scripts/. It writes to stdout via ``print`` — same
    capture pattern works."""
    res = AuditResult(
        name="doctor",
        purpose="Config health (env + adapters + budgets)",
    )
    try:
        from cli import _cmd_health
    except ImportError as exc:
        res.skipped = True
        res.skip_reason = f"cli._cmd_health import failed: {exc}"
        return res
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            _cmd_health()
        res.rc = 0
        res.output = buf.getvalue()
    except SystemExit as exc:
        try:
            res.rc = int(exc.code) if exc.code is not None else 0
        except (TypeError, ValueError):
            res.rc = 2
        res.output = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        res.rc = -1
        res.output = buf.getvalue()
        res.error = f"{type(exc).__name__}: {exc}"
    return res


def collect_audits(
    *,
    skip: tuple[str, ...] = (),
) -> list[AuditResult]:
    """Run every audit in deterministic order. Each entry is
    safe to skip with ``--skip name1,name2``."""
    audits: list[AuditResult] = []

    # Doctor is the cheapest probe — run first so we surface
    # config issues before the network-based audits time out.
    if "doctor" not in skip:
        audits.append(_run_doctor())

    plan: list[tuple[str, str, str]] = [
        ("scope_audit",
         "scripts.deguar_scope_audit",
         "Shopify OAuth scopes (granted vs needs)"),
        ("collection_check",
         "scripts.deguar_collection_check",
         "Smart collections populated"),
        ("webhook_check",
         "scripts.deguar_webhook_check",
         "Order learning-loop webhooks wired"),
        ("tracking_check",
         "scripts.deguar_tracking_check",
         "Meta / TikTok / GA pixels firing"),
        ("checkout_check",
         "scripts.deguar_checkout_check",
         "Payment + shipping + URL reachability"),
        ("live_audit",
         "scripts.deguar_live_audit",
         "Images + duplicates + pricing"),
    ]
    for name, modpath, purpose in plan:
        if name in skip:
            audits.append(AuditResult(
                name=name, purpose=purpose,
                skipped=True, skip_reason="--skip flag",
            ))
            continue
        try:
            mod: Any = __import__(modpath, fromlist=["main"])
            main_fn = mod.main
        except Exception as exc:  # noqa: BLE001
            audits.append(AuditResult(
                name=name, purpose=purpose,
                skipped=True,
                skip_reason=f"import failed: {exc}",
            ))
            continue
        audits.append(_run_audit(name, purpose, main_fn))

    return audits


# ── Markdown rendering ───────────────────────────────────


def render_markdown(report: HealthReport) -> str:
    counts = report.counts()
    lines: list[str] = []
    lines.append(f"# Deguar health report — {report.generated_at}")
    lines.append("")
    lines.append(f"**Store:** `{report.store}`")
    lines.append("")
    lines.append(f"## Verdict: **{report.verdict}**")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for s in ("ok", "warning", "blocked", "error", "skipped"):
        lines.append(f"| {s} | {counts.get(s, 0)} |")
    lines.append("")
    lines.append("## Per-audit summary")
    lines.append("")
    lines.append("| Audit | Status | rc | Purpose |")
    lines.append("|---|---|---|---|")
    for a in report.audits:
        rc_disp = "—" if a.skipped else str(a.rc)
        lines.append(
            f"| `{a.name}` | {a.emoji} {a.status} | {rc_disp} "
            f"| {a.purpose} |",
        )
    lines.append("")
    lines.append("## Detail (collapsed)")
    lines.append("")
    for a in report.audits:
        title = f"{a.emoji} {a.name} (rc={a.rc})"
        if a.skipped:
            title = f"{a.emoji} {a.name} (skipped: {a.skip_reason})"
        lines.append(f"<details><summary>{title}</summary>")
        lines.append("")
        lines.append("```text")
        if a.skipped:
            lines.append(f"(skipped — {a.skip_reason})")
        else:
            lines.append(a.output.rstrip() or "(no output)")
            if a.error:
                lines.append("")
                lines.append("ERROR:")
                lines.append(a.error.rstrip())
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_summary(report: HealthReport) -> str:
    """Single-line + table summary suitable for stdout / cron
    log + paste-to-Telegram."""
    counts = report.counts()
    lines: list[str] = []
    lines.append(f"Deguar health — {report.generated_at}")
    lines.append(f"Verdict: {report.verdict}  "
                 f"(ok={counts['ok']} "
                 f"warn={counts['warning']} "
                 f"blocked={counts['blocked']} "
                 f"err={counts['error']} "
                 f"skip={counts['skipped']})")
    lines.append("")
    for a in report.audits:
        rc_disp = "  -" if a.skipped else f"{a.rc:>3d}"
        lines.append(
            f"  {a.emoji} {a.name:18s}  rc={rc_disp}  {a.purpose}",
        )
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out", default="reports/",
        help=(
            "Directory to write the markdown report into. "
            "Filename is YYYY-MM-DD-health.md. Default: reports/. "
            "Pass '-' to skip writing the file (stdout only)."
        ),
    )
    ap.add_argument(
        "--skip", default="",
        help=(
            "CSV of audit names to skip "
            "(doctor, scope_audit, collection_check, "
            "webhook_check, tracking_check, checkout_check, "
            "live_audit)."
        ),
    )
    args = ap.parse_args(argv)

    # Resolve store name from env (don't require it — doctor
    # check will surface missing creds anyway)
    store = (
        os.environ.get("SHOPAI_SHOPIFY_URL") or "(not configured)"
    )
    today = dt.datetime.now().strftime("%Y-%m-%d")
    skip = tuple(
        s.strip() for s in args.skip.split(",") if s.strip()
    )

    audits = collect_audits(skip=skip)
    report = HealthReport(
        generated_at=today, store=store, audits=audits,
    )

    # Always print summary to stdout (cron-friendly)
    print(render_summary(report))

    # Optionally write markdown
    if args.out != "-":
        md = render_markdown(report)
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f"{today}-health.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"\nWritten: {path}")

    # Exit code mirrors verdict
    return {
        "READY": 0,
        "WARNINGS": 1,
        "BLOCKED": 2,
        "UNKNOWN": 2,
    }[report.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
