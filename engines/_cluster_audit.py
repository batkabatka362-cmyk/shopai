"""Cluster topology + risk taxonomy CI audit.

The 9th institutional gate. Protects the Tier 2b substrate:
  - 10 cluster definitions stable
  - Every domain engine mapped to exactly one cluster
  - Every wired engine has a known risk classification
  - No engine appears in multiple clusters
  - Risk taxonomy doesn't silently grow destructive count

Fires as part of ``shopai audit`` + CI gate. If any
invariant breaks, the build fails -- catches a refactor
that drops a cluster, miscategorizes an engine, or
introduces a stealth destructive writer.

Mirrors the pattern of the existing 8 audits (Pattern K /
OAuth / Pattern Y / Pattern I / Pattern J / Pattern Z /
Pattern Q / wireup_resolve).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClusterAuditReport:
    violations: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def audit_clusters() -> ClusterAuditReport:
    """Run every cluster invariant. Returns violations + info."""
    from engines._clusters import (
        list_clusters,
        unassigned_domain_engines,
    )
    from engines._writeback_risk import classify_writers

    report = ClusterAuditReport()

    # Invariant 1: exactly 10 clusters
    clusters = list_clusters()
    if len(clusters) != 10:
        report.violations.append(
            f"cluster count drifted: expected 10, got "
            f"{len(clusters)}"
        )
    else:
        report.info.append(
            f"10 cluster definitions present"
        )

    # Invariant 2: every cluster has a KPI + description +
    # non-empty members
    for c in clusters:
        if not c.kpi:
            report.violations.append(
                f"cluster '{c.name}' missing KPI"
            )
        if not c.description:
            report.violations.append(
                f"cluster '{c.name}' missing description"
            )
        if not c.members:
            report.violations.append(
                f"cluster '{c.name}' has no members"
            )

    # Invariant 3: no engine in multiple clusters
    seen: dict[str, str] = {}
    for c in clusters:
        for member in c.members:
            if member in seen:
                report.violations.append(
                    f"engine '{member}' appears in both "
                    f"'{seen[member]}' and '{c.name}' clusters"
                )
            else:
                seen[member] = c.name

    # Invariant 4: cluster size bounds (3-25 members)
    for c in clusters:
        size = len(c.members)
        if size < 3:
            report.violations.append(
                f"cluster '{c.name}' has only {size} "
                "member(s) -- minimum is 3 (else merge "
                "with sibling)"
            )
        if size > 25:
            report.violations.append(
                f"cluster '{c.name}' has {size} members "
                "-- maximum is 25 (else split)"
            )

    # Invariant 5: no unassigned domain engines
    unassigned = unassigned_domain_engines()
    if unassigned:
        report.violations.append(
            f"unassigned domain engines: "
            f"{sorted(unassigned)} -- add to a cluster or "
            "_ORCHESTRATOR_UTILITIES allow-list"
        )

    # Invariant 6: risk classifier covers every writer
    try:
        risk = classify_writers("engines")
    except Exception as exc:  # noqa: BLE001
        report.violations.append(
            f"risk classifier failed: {exc}"
        )
        return report

    unknown_risks = [
        w for w in risk.writers if w.risk == "unknown"
    ]
    if unknown_risks:
        names = sorted({w.engine for w in unknown_risks})
        report.violations.append(
            f"writers with unknown risk class: {names} -- "
            "declare _WRITEBACK_RISK or add capability to "
            "the hint set in engines/_writeback_risk.py"
        )

    # Invariant 7: additive >> modification (architectural
    # invariant matching the test)
    additive = risk.count("additive")
    modification = risk.count("modification")
    destructive = risk.count("destructive")
    if additive < 5 * modification and modification > 0:
        report.violations.append(
            f"additive/modification ratio drifted: "
            f"additive={additive}, modification={modification}. "
            "Additive should dominate -- modifications need "
            "operator approval at fire-time."
        )
    if destructive > 3:
        report.violations.append(
            f"too many destructive writers: {destructive}. "
            "Hard cap is 3 -- destructive bypasses normal "
            "approval flow."
        )

    report.info.append(
        f"writer risk: {additive} additive, "
        f"{modification} modification, "
        f"{destructive} destructive"
    )

    return report
